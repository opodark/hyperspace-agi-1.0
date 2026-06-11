# HyperSpace-AGI v1.0 - Node Server con P2P + Shared Dreams + Auto-pull
from __future__ import annotations
import asyncio
import logging
import os
import uuid
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from shared.settings import settings
from node.memory.tiered_store import TieredMemoryStore
from node.runtime.agent_runtime import AgentRuntime
from node.runtime.gossip_service import GossipService, PeerInfo
from node.runtime.node_state import NodeStateManager, DreamEntry
from node.runtime.auto_pull import run_auto_pull
from node.security import ClusterSecretMiddleware, CLUSTER_SECRET

logger = logging.getLogger('node')

NODE_ID     = os.getenv('NODE_ID', 'node-default')
NODE_HOST   = os.getenv('NODE_HOST', NODE_ID)
NODE_PORT   = int(os.getenv('NODE_API_PORT', '8765'))
MODELS      = os.getenv('DEFAULT_AGENT_MODEL', 'qwen2.5:7b').split(',')
NODE_RAM_GB = float(os.getenv('NODE_RAM_GB', '0'))

_self_info = PeerInfo.from_env(node_id=NODE_ID, host=NODE_HOST, port=NODE_PORT, models=MODELS)
_gossip    = GossipService(self_info=_self_info)
_memory    = TieredMemoryStore()
_agent     = AgentRuntime(memory_store=_memory)
_state     = NodeStateManager(node_id=NODE_ID)

_auto_pull_result: dict = {'status': 'pending'}


async def _run_auto_pull_bg() -> None:
    global _auto_pull_result
    try:
        logger.info(f'AutoPull: avvio per {NODE_ID} (RAM={NODE_RAM_GB}GB)')
        result = await run_auto_pull()
        _auto_pull_result = result
        pulled = result.get('pulled', [])
        if pulled:
            logger.info(f'AutoPull: completato — pullati {pulled}')
        else:
            logger.info('AutoPull: tutti i modelli già presenti ✅')
    except Exception as e:
        _auto_pull_result = {'status': 'error', 'reason': str(e)}
        logger.error(f'AutoPull: errore {e}')


async def _propagate_dream(dream: DreamEntry) -> None:
    import httpx
    peers = _gossip.get_peers()
    headers = {'X-HyperSpace-Secret': CLUSTER_SECRET} if CLUSTER_SECRET else {}
    for peer in peers:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f'{peer.url}/dreams/receive',
                                  json=dream.to_dict(), headers=headers)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    if CLUSTER_SECRET:
        logger.info(f'Node {NODE_ID}: cluster secret attivo 🔒')
    else:
        logger.warning(f'Node {NODE_ID}: HYPERSPACE_CLUSTER_SECRET non impostato')
    await _gossip.start()
    if NODE_RAM_GB > 0:
        asyncio.create_task(_run_auto_pull_bg())
    else:
        _auto_pull_result.update({'status': 'skipped', 'reason': 'NODE_RAM_GB not set'})
    yield
    await _gossip.stop()


app = FastAPI(
    title=f'HyperSpace-AGI Node [{_self_info.display_name()}]',
    version='1.0.0',
    lifespan=lifespan
)

app.add_middleware(ClusterSecretMiddleware)


@app.get('/health')
async def health() -> dict:
    return {
        'status':   'ok', 'service': 'node', 'version': '1.0.0',
        'node_id':  NODE_ID, 'nickname': _self_info.nickname,
        'location': _self_info.location,
        'ram_gb':   NODE_RAM_GB,
        'auto_pull': _auto_pull_result.get('status', 'pending'),
        'cluster_secret_active': bool(CLUSTER_SECRET),
        **_state.get_status(),
    }


@app.get('/auto-pull/status')
async def auto_pull_status() -> dict:
    return {'node_id': NODE_ID, 'ram_gb': NODE_RAM_GB, **_auto_pull_result}


class ChatRequest(BaseModel):
    session_id: str
    message: str
    model_alias: str = 'auto'
    system_prompt: str | None = None


@app.post('/chat')
async def chat(req: ChatRequest) -> dict:
    _state.record_request()
    _gossip.update_self_state('active', load=min(_state._request_count / 100, 1.0))
    try:
        response = await _agent.run(
            session_id=req.session_id, user_message=req.message,
            model_alias=req.model_alias, system_prompt=req.system_prompt,
        )
        return {'session_id': req.session_id, 'response': response}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.get('/memory/{session_id}')
async def list_memory(session_id: str) -> dict:
    records = await _memory.list_session(session_id)
    return {'session_id': session_id, 'count': len(records), 'records': [r.model_dump() for r in records]}


@app.get('/memory/{session_id}/quarantine')
async def list_quarantine(session_id: str) -> dict:
    records = await _memory.list_quarantine(session_id)
    return {'session_id': session_id, 'quarantined': [r.model_dump() for r in records]}


@app.get('/memory/contested')
async def list_contested() -> dict:
    records = await _memory.list_contested()
    return {'count': len(records), 'contested': [r.model_dump() for r in records]}


@app.post('/memory/prune')
async def prune_memory(threshold: float = 0.25) -> dict:
    pruned_score = await _memory.prune_low_score_speculative(threshold)
    pruned_ttl   = await _memory.prune_expired_ttl()
    return {'pruned_low_score': pruned_score, 'pruned_ttl': pruned_ttl}


@app.post('/gossip/heartbeat')
async def gossip_heartbeat(peer: dict) -> dict:
    _gossip.register_peer(peer)
    return {
        'node_id':  NODE_ID, 'nickname': _self_info.nickname,
        'state':    _state.state, 'load': _state.load,
        'peers':    [p.to_dict() for p in _gossip.get_peers()],
    }


@app.get('/gossip/peers')
async def list_peers() -> dict:
    return {
        'self':        _gossip.self_to_dict(),
        'peers':       [p.to_dict() for p in _gossip.get_all_peers()],
        'alive_count': len(_gossip.get_peers()),
        'total':       len(_gossip.get_all_peers()),
    }


@app.get('/dreams')
async def list_dreams() -> dict:
    return _state.get_status()


@app.post('/dreams/add')
async def add_dream(content: str, score: float = 0.75) -> dict:
    dream = DreamEntry(
        dream_id    = str(uuid.uuid4())[:8],
        content     = content,
        score       = score,
        origin_node = NODE_ID,
    )
    _state.add_dream(dream)
    _gossip.update_self_state('dreaming')
    asyncio.create_task(_propagate_dream(dream))
    return dream.to_dict()


@app.post('/dreams/receive')
async def receive_dream(data: dict) -> dict:
    dream = _state.receive_dream(data)
    if dream is None:
        return {'status': 'already_known', 'dream_id': data.get('dream_id')}
    return {'status': 'received', **dream.to_dict()}


@app.post('/dreams/{dream_id}/vote')
async def vote_dream(dream_id: str) -> dict:
    result = _state.vote_dream(dream_id, voter_node=NODE_ID)
    if result is None:
        return JSONResponse(status_code=404, content={'error': 'dream not found'})
    asyncio.create_task(_propagate_dream(result))
    return result.to_dict()


@app.post('/dreams/{dream_id}/retract')
async def retract_dream(dream_id: str) -> dict:
    result = _state.resolve_dream(dream_id, 'retracted')
    if result is None:
        return JSONResponse(status_code=404, content={'error': 'dream not found'})
    _gossip.update_self_state('active')
    return result.to_dict()


if __name__ == '__main__':
    uvicorn.run('node.server:app', host='0.0.0.0', port=NODE_PORT, reload=False)
