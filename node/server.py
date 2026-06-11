# HyperSpace-AGI v1.1 - Node Server con Dream Engine
# Basato sul server originale v5.9, aggiunge dream engine autonomo
from __future__ import annotations
import asyncio
import logging
import os
import time
import uuid
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from shared.settings import settings
from node.memory.tiered_store import TieredMemoryStore
from node.runtime.agent_runtime import AgentRuntime
from node.runtime.node_state import NodeStateManager, DreamEntry
from node.runtime.dream_engine import DreamEngine

logger = logging.getLogger('node')
logging.basicConfig(level=logging.INFO)

NODE_ID      = os.getenv('NODE_ID', f'node-{uuid.uuid4().hex[:6]}')
NODE_NICKNAME = os.getenv('NODE_NICKNAME', NODE_ID)
OLLAMA_URL   = os.getenv('OLLAMA_BASE_URL', settings.ollama_base_url)
DEFAULT_MODEL = os.getenv('DEFAULT_AGENT_MODEL', settings.default_agent_model)

# Peer URLs per propagazione dream (separati da virgola)
NODE_PEERS_RAW = os.getenv('NODE_PEERS', '')
NODE_PEER_URLS = [u.strip() for u in NODE_PEERS_RAW.split(',') if u.strip()]

_memory = TieredMemoryStore()
_agent  = AgentRuntime(memory_store=_memory)
_state  = NodeStateManager(node_id=NODE_ID)
_dream_engine = DreamEngine(
    node_id       = NODE_ID,
    state_manager = _state,
    memory_store  = _memory,
    ollama_url    = OLLAMA_URL,
    model_id      = DEFAULT_MODEL,
    peer_urls     = NODE_PEER_URLS,
)


class ChatRequest(BaseModel):
    session_id:    str
    message:       str
    model_alias:   str = 'auto'
    system_prompt: str | None = None


class DreamAddRequest(BaseModel):
    content: str
    score:   float = 0.5


class DreamVoteRequest(BaseModel):
    voter_node: str = ''


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f'Node {NODE_ID} ({NODE_NICKNAME}) avviato')
    await _dream_engine.start()
    yield
    await _dream_engine.stop()


app = FastAPI(
    title='HyperSpace-AGI Node',
    version='1.1.0',
    lifespan=lifespan,
)


@app.get('/health')
async def health() -> dict:
    return {
        'status': 'ok',
        'service': 'node',
        'node_id': NODE_ID,
        'version': '1.1.0',
        'dream_engine': 'running',
    }


@app.post('/chat')
async def chat(req: ChatRequest) -> dict:
    _state.record_request()
    try:
        response = await _agent.run(
            session_id=req.session_id, user_message=req.message,
            model_alias=req.model_alias, system_prompt=req.system_prompt,
        )
        return {'session_id': req.session_id, 'response': response, 'node_id': NODE_ID}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.get('/status')
async def node_status() -> dict:
    return _state.get_status()


@app.get('/dreams')
async def list_dreams() -> dict:
    return {'node_id': NODE_ID, 'nickname': NODE_NICKNAME, **_state.get_status()}


@app.post('/dreams/add')
async def add_dream(req: DreamAddRequest) -> dict:
    dream = DreamEntry(
        dream_id    = f'dream-{NODE_ID}-{uuid.uuid4().hex[:8]}',
        content     = req.content,
        score       = req.score,
        origin_node = NODE_ID,
    )
    _state.add_dream(dream)
    return {'ok': True, 'dream_id': dream.dream_id}


@app.post('/dreams/receive')
async def receive_dream(data: dict) -> dict:
    dream = _state.receive_dream(data)
    if dream and dream.score > 0.5:
        _state.vote_dream(dream.dream_id, voter_node=NODE_ID)
    return {'ok': True, 'dream_id': data.get('dream_id')}


@app.post('/dreams/{dream_id}/vote')
async def vote_dream(dream_id: str, req: DreamVoteRequest) -> dict:
    dream = _state.vote_dream(dream_id, voter_node=req.voter_node or NODE_ID)
    if not dream:
        return JSONResponse(status_code=404, content={'error': 'Dream not found'})
    return dream.to_dict()


@app.get('/memory/{session_id}')
async def list_memory(session_id: str) -> dict:
    records = await _memory.list_session(session_id)
    return {'session_id': session_id, 'count': len(records), 'records': [r.model_dump() for r in records]}


@app.get('/memory/{session_id}/quarantine')
async def list_quarantine(session_id: str) -> dict:
    records = await _memory.list_quarantine(session_id)
    return {'session_id': session_id, 'quarantined': [r.model_dump() for r in records]}


@app.post('/memory/prune')
async def prune_memory(threshold: float = 0.25) -> dict:
    pruned_score = await _memory.prune_low_score_speculative(threshold)
    pruned_ttl   = await _memory.prune_expired_ttl()
    return {'pruned_low_score': pruned_score, 'pruned_ttl': pruned_ttl}


@app.get('/gossip/peers')
async def gossip_peers() -> dict:
    """Stub — compatibilita' dashboard."""
    return {'self': {'node_id': NODE_ID, 'nickname': NODE_NICKNAME, 'alive': True}, 'peers': []}


if __name__ == '__main__':
    uvicorn.run('node.server:app', host='0.0.0.0', port=settings.node_api_port, reload=False)
