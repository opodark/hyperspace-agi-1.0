# HyperSpace-AGI v1.1 - Node Agent Server con Dream Engine
from __future__ import annotations
import asyncio
import logging
import os
import time
import uuid
import httpx
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from shared.settings import settings
from node.memory.tiered_store import TieredMemoryStore
from node.runtime.node_state import NodeStateManager, DreamEntry
from node.runtime.dream_engine import DreamEngine
from node.gossip.gossip_manager import GossipManager
from node.ollama_pull_service import OllamaPullService

logger = logging.getLogger('node')
logging.basicConfig(level=logging.INFO)

# --- Identita' nodo ---
NODE_ID       = os.getenv('NODE_ID', f'node-{uuid.uuid4().hex[:6]}')
NODE_NICKNAME = os.getenv('NODE_NICKNAME', NODE_ID)
NODE_HOST     = os.getenv('NODE_HOST', '127.0.0.1')
NODE_COLOR    = os.getenv('NODE_COLOR', '#6366f1')
NODE_LOCATION = os.getenv('NODE_LOCATION', 'Unknown')
NODE_TAGS_RAW = os.getenv('NODE_TAGS', 'dev')
NODE_TAGS     = [t.strip() for t in NODE_TAGS_RAW.split(',') if t.strip()]
NODE_OWNER    = os.getenv('NODE_OWNER', '')
NODE_AVATAR_STYLE = os.getenv('NODE_AVATAR_STYLE', 'bottts')
NODE_RAM_GB   = int(os.getenv('NODE_RAM_GB', '8'))
NODE_API_PORT = int(os.getenv('NODE_API_PORT', str(settings.node_api_port)))
CLUSTER_SECRET = os.getenv('HYPERSPACE_CLUSTER_SECRET', '')

# --- Servizi ---
OLLAMA_URL       = os.getenv('OLLAMA_BASE_URL', settings.ollama_base_url)
DEFAULT_MODEL    = os.getenv('DEFAULT_AGENT_MODEL', settings.default_agent_model)
AUTHORITY_URL    = os.getenv('AUTHORITY_URL', f'http://authority:{settings.authority_api_port}')

# Peer URLs per gossip e dream propagation (separati da virgola)
NODE_PEERS_RAW = os.getenv('NODE_PEERS', '')
NODE_PEER_URLS = [u.strip() for u in NODE_PEERS_RAW.split(',') if u.strip()]

GOSSIP_INTERVAL  = int(os.getenv('GOSSIP_INTERVAL_SEC', '30'))
ANNOUNCE_INTERVAL = int(os.getenv('ANNOUNCE_INTERVAL_SEC', '60'))

# --- Init componenti ---
_memory  = TieredMemoryStore(state_dir='/node/shared/memory')
_state   = NodeStateManager(node_id=NODE_ID)
_dream_engine = DreamEngine(
    node_id      = NODE_ID,
    state_manager= _state,
    memory_store = _memory,
    ollama_url   = OLLAMA_URL,
    model_id     = DEFAULT_MODEL,
    peer_urls    = NODE_PEER_URLS,
)
_gossip  = GossipManager(
    node_id        = NODE_ID,
    host           = NODE_HOST,
    port           = NODE_API_PORT,
    nickname       = NODE_NICKNAME,
    color          = NODE_COLOR,
    location       = NODE_LOCATION,
    tags           = NODE_TAGS,
    owner          = NODE_OWNER,
    avatar_style   = NODE_AVATAR_STYLE,
    ram_gb         = NODE_RAM_GB,
    authority_url  = AUTHORITY_URL,
    peer_urls      = NODE_PEER_URLS,
    state_manager  = _state,
    gossip_interval_sec   = GOSSIP_INTERVAL,
    announce_interval_sec = ANNOUNCE_INTERVAL,
)


# --- Request models ---
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


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f'Node {NODE_ID} ({NODE_NICKNAME}) avviato su porta {NODE_API_PORT}')
    await _gossip.start()
    await _dream_engine.start()   # <-- avvia dream engine
    yield
    await _gossip.stop()
    await _dream_engine.stop()


app = FastAPI(
    title=f'HyperSpace Node — {NODE_NICKNAME}',
    version='1.1.0',
    lifespan=lifespan,
)


def _check_secret(secret: str | None) -> None:
    if CLUSTER_SECRET and secret != CLUSTER_SECRET:
        raise HTTPException(status_code=403, detail='Invalid cluster secret')


# --- Endpoints ---

@app.get('/health')
async def health() -> dict:
    return {
        'status':   'ok',
        'node_id':  NODE_ID,
        'nickname': NODE_NICKNAME,
        'version':  '1.1.0',
        'dream_engine': 'running',
    }


@app.get('/status')
async def node_status() -> dict:
    return _state.get_status()


@app.post('/chat')
async def chat(
    req: ChatRequest,
    x_hyperspace_secret: str | None = Header(default=None),
) -> dict:
    _check_secret(x_hyperspace_secret)
    _state.record_request()

    model_id = DEFAULT_MODEL
    messages = []
    if req.system_prompt:
        messages.append({'role': 'system', 'content': req.system_prompt})
    messages.append({'role': 'user', 'content': req.message})

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f'{OLLAMA_URL}/api/chat',
                json={'model': model_id, 'messages': messages, 'stream': False},
            )
            resp.raise_for_status()
            data    = resp.json()
            content = data.get('message', {}).get('content', '')
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Ollama error: {e}')

    # Salva in memoria episodica
    from shared.domain.models import MemoryRecord, MemoryTier, ContestStatus
    for role, text in [('user', req.message), ('assistant', content)]:
        rec = MemoryRecord(
            memory_id=str(uuid.uuid4()),
            session_id=req.session_id,
            role=role,
            content=text,
            tier=MemoryTier.EPISODIC,
            score=0.5,
        )
        await _memory.add(rec)

    return {
        'node_id':   NODE_ID,
        'nickname':  NODE_NICKNAME,
        'response':  content,
        'model_id':  model_id,
        'timestamp': time.time(),
    }


@app.get('/dreams')
async def list_dreams() -> dict:
    return {
        'node_id':  NODE_ID,
        'nickname': NODE_NICKNAME,
        **_state.get_status(),
    }


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
    """Riceve un dream da un peer. Lo vota automaticamente se score > 0.5."""
    dream = _state.receive_dream(data)
    if dream and dream.score > 0.5:
        _state.vote_dream(dream.dream_id, voter_node=NODE_ID)
    return {'ok': True, 'dream_id': data.get('dream_id')}


@app.post('/dreams/{dream_id}/vote')
async def vote_dream(dream_id: str, req: DreamVoteRequest) -> dict:
    dream = _state.vote_dream(dream_id, voter_node=req.voter_node or NODE_ID)
    if not dream:
        raise HTTPException(status_code=404, detail='Dream not found')
    return dream.to_dict()


@app.get('/memory')
async def list_memory(session_id: str = 'default', tier: str = '') -> dict:
    from shared.domain.models import MemoryTier
    if tier:
        records = await _memory.list_recent_by_tier(MemoryTier(tier), limit=50)
    else:
        records = await _memory.list_session(session_id)
    return {'records': [r.__dict__ for r in records]}


@app.get('/gossip/peers')
async def gossip_peers() -> dict:
    return _gossip.get_peers_status()


if __name__ == '__main__':
    uvicorn.run(
        'node.server:app',
        host='0.0.0.0',
        port=NODE_API_PORT,
        reload=False,
    )
