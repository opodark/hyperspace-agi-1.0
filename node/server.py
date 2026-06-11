# HyperSpace-AGI v1.1 - Node Server con Dream Engine + Idle Chat Engine
from __future__ import annotations
import asyncio
import logging
import os
import random
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
from node.runtime.idle_chat_engine import IdleChatEngine
from shared.domain.models import MemoryRecord, MemoryTier

logger = logging.getLogger('node')
logging.basicConfig(level=logging.INFO)

NODE_ID       = os.getenv('NODE_ID', f'node-{uuid.uuid4().hex[:6]}')
NODE_NICKNAME = os.getenv('NODE_NICKNAME', NODE_ID)
OLLAMA_URL    = os.getenv('OLLAMA_BASE_URL', settings.ollama_base_url)
DEFAULT_MODEL = os.getenv('DEFAULT_AGENT_MODEL', settings.default_agent_model)

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
_idle_chat = IdleChatEngine(
    node_id       = NODE_ID,
    state_manager = _state,
    memory_store  = _memory,
    ollama_url    = OLLAMA_URL,
    model_id      = DEFAULT_MODEL,
    peer_urls     = NODE_PEER_URLS,
)

# Topic sintetici per seed-memories
_SEED_TOPICS = [
    ("Gli agenti distribuiti si coordinano senza autorità centrale usando protocolli gossip",
     "Esatto: ogni nodo mantiene una vista parziale della rete e propaga informazioni ai vicini. La convergenza avviene in O(log n) round."),
    ("La memoria semantica si forma dalla ripetizione e consolidamento di pattern episodici",
     "Il processo è simile al sonno REM umano: durante l'idle il sistema riattiva tracce episodiche e le astrae in conoscenza generalizzata."),
    ("Un modello quantizzato a 4bit perde circa il 3% di accuracy ma guadagna 4x in velocità",
     "La quantizzazione GGUF con Q4_K_M è il miglior compromesso su hardware consumer: permette di girare un 7B in 4GB di VRAM."),
    ("Il dreaming nei sistemi IA serve a comprimere e generalizzare esperienze passate",
     "I dream con score alto vengono promossi a memoria SEMANTIC e condivisi con la rete, aumentando la conoscenza collettiva."),
    ("Kademlia DHT usa XOR distance per trovare nodi in O(log n) hop",
     "Ogni nodo mantiene k-bucket per ogni bit di distanza. Il lookup converge rapidamente anche in reti con migliaia di peer."),
    ("I transformer attention heads specializzati emergono spontaneamente durante il training",
     "Alcuni head si specializzano in coreference, altri in relazioni sintattiche. Questo suggerisce che la struttura emerge dai dati, non dall'architettura."),
    ("La temperatura del softmax controlla il trade-off tra creatività e coerenza",
     "Temperature basse (0.1-0.3) producono output deterministici, alte (0.8-1.2) output creativi ma meno coerenti. Per ragionamento si usa 0.1-0.3."),
    ("Multi-agent systems raggiungono emergenza comportamentale oltre una soglia critica di nodi",
     "Con 3+ nodi la rete inizia a mostrare comportamenti non programmati: specializzazione spontanea, load balancing adattivo, resilienza."),
    ("Il contesto finestra di 8k token è sufficiente per il 95% dei task conversazionali",
     "La memoria esterna (RAG + tiered store) copre il resto. L'injection selettiva di memorie rilevanti è più efficiente di un contesto enorme."),
    ("La memoria episodica decade esponenzialmente senza rinforzo semantico",
     "Per questo il dream engine promuove i pattern ricorrenti a SEMANTIC: sono informazioni che il nodo ha incontrato abbastanza volte da meritare persistenza."),
    ("Il load balancing least-loaded riduce la latenza media del 40% rispetto al round-robin",
     "In HyperSpace il dispatcher sceglie il nodo con load minore tra quelli compatibili con il modello richiesto."),
    ("I Small Language Models sotto i 10B parametri sono sufficienti per la maggior parte dei task agentici",
     "Pianificazione, tool use, summarization e RAG non richiedono GPT-4. Un Qwen2.5 7B quantizzato gestisce bene questi task in locale."),
]


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


class SeedMemoriesRequest(BaseModel):
    count:      int   = 8       # quante memorie iniettare (max 12)
    trigger_dream: bool = True  # forza subito una sessione di dreaming
    custom_topics: list[str] = []  # topic custom opzionali


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f'Node {NODE_ID} ({NODE_NICKNAME}) avviato')
    await _dream_engine.start()
    await _idle_chat.start()
    yield
    await _dream_engine.stop()
    await _idle_chat.stop()


app = FastAPI(
    title='HyperSpace-AGI Node',
    version='1.1.0',
    lifespan=lifespan,
)


@app.get('/health')
async def health() -> dict:
    return {
        'status':           'ok',
        'service':          'node',
        'node_id':          NODE_ID,
        'version':          '1.1.0',
        'dream_engine':     'running',
        'idle_chat_engine': 'running',
    }


@app.post('/chat')
async def chat(req: ChatRequest) -> dict:
    if not req.session_id.startswith('synthetic-idle-'):
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


@app.post('/debug/seed-memories')
async def seed_memories(req: SeedMemoriesRequest) -> dict:
    """
    Inietta memorie episodiche sintetiche e opzionalmente triggera il dream engine.
    Utile per testare il dreaming senza aspettare conversazioni reali o peer connessi.
    """
    session_id = f'seed-{uuid.uuid4().hex[:8]}'
    count      = min(req.count, 12)
    saved      = []

    # Scegli topic: custom se forniti, altrimenti random dai seed
    if req.custom_topics:
        pairs = [(t, f'Riflessione su: {t}') for t in req.custom_topics[:count]]
    else:
        pool  = random.sample(_SEED_TOPICS, min(count, len(_SEED_TOPICS)))
        pairs = pool[:count]

    for user_text, assistant_text in pairs:
        for role, text in [('user', user_text), ('assistant', assistant_text)]:
            rec = MemoryRecord(
                memory_id  = str(uuid.uuid4()),
                session_id = session_id,
                role       = role,
                content    = text,
                tier       = MemoryTier.EPISODIC,
                score      = 0.5,
            )
            await _memory.add(rec)
        saved.append(user_text[:80])

    logger.info(f'[{NODE_ID}] Seed: {len(saved)*2} memorie episodiche iniettate (session={session_id})')

    # Triggera dreaming immediatamente resettando il cooldown
    if req.trigger_dream:
        _dream_engine._last_dream  = 0.0   # azzera cooldown
        _state._last_request       = 0.0   # simula idle lungo
        asyncio.create_task(_dream_engine._dreaming_session())
        logger.info(f'[{NODE_ID}] Dream session triggerata manualmente')

    return {
        'ok':          True,
        'session_id':  session_id,
        'injected':    len(saved) * 2,
        'topics':      saved,
        'dream_triggered': req.trigger_dream,
        'tip':         'Monitora con: curl http://localhost:8765/dreams | python3 -m json.tool',
    }


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
    return {'self': {'node_id': NODE_ID, 'nickname': NODE_NICKNAME, 'alive': True}, 'peers': []}


if __name__ == '__main__':
    uvicorn.run('node.server:app', host='0.0.0.0', port=settings.node_api_port, reload=False)
