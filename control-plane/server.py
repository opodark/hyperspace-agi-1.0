# HyperSpace-AGI v1.1 - Control Plane Server
# FastAPI su porta 8768 — con dispatcher cross-nodo
from __future__ import annotations
import asyncio
import logging
import os
import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from shared.domain.models import UserRequest, ChatCompletionsRequest
from shared.settings import settings
from control_plane.request_classifier import RequestClassifier
from control_plane.smart_router import SmartRouter
from control_plane.runtime_store import ControlPlaneRuntimeStore
from control_plane.node_dispatcher import NodeDispatcher

logger = logging.getLogger('control_plane')
logging.basicConfig(level=logging.INFO)

_classifier  = RequestClassifier()
_router      = SmartRouter()
_store       = ControlPlaneRuntimeStore()
_dispatcher  = NodeDispatcher()

_AUTHORITY_URL = f'http://authority:{settings.authority_api_port}'
_WORKER_URL    = f'http://worker:{settings.worker_api_port}'
_OLLAMA_URL    = settings.ollama_base_url
_SELF_NODE_ID  = os.getenv('NODE_ID', 'control-plane')

# Abilita/disabilita dispatch cross-nodo (default: True)
_CROSS_NODE_ENABLED = os.getenv('CROSS_NODE_DISPATCH', 'true').lower() == 'true'


async def _ensure_model_hot(model_id: str) -> bool:
    """Verifica se il modello e' presente in Ollama, altrimenti avvia il pull."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f'{_OLLAMA_URL}/api/tags')
            tags = r.json().get('models', [])
            names = [m.get('name', '') for m in tags]
            if any(model_id in n for n in names):
                return True
            logger.info(f'Modello {model_id} non presente, avvio pull...')
            async with httpx.AsyncClient(timeout=600.0) as pull_client:
                async with pull_client.stream(
                    'POST', f'{_OLLAMA_URL}/api/pull', json={'name': model_id}
                ) as stream:
                    async for line in stream.aiter_lines():
                        if '"status":"success"' in line:
                            logger.info(f'Pull {model_id} completato.')
                            return True
            return False
    except Exception as e:
        logger.warning(f'_ensure_model_hot error: {e}')
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f'Startup: verifico modello default {settings.default_agent_model}')
    logger.info(f'Cross-node dispatch: {"ABILITATO" if _CROSS_NODE_ENABLED else "DISABILITATO"}')
    asyncio.create_task(_ensure_model_hot(settings.default_agent_model))
    yield


app = FastAPI(
    title='HyperSpace-AGI Control Plane',
    description='Smart Routing 4-level + Cross-Node Dispatch + Catalog + Votes + Replay proxy',
    version='1.1.0',
    lifespan=lifespan,
)


@app.get('/health')
async def health() -> dict:
    return {
        'status': 'ok',
        'service': 'control-plane',
        'version': '1.1.0',
        'cross_node_dispatch': _CROSS_NODE_ENABLED,
    }


@app.post('/route')
async def route_request(request: UserRequest) -> dict:
    """Classifica e ruota una UserRequest. Ritorna ExecutionPlan."""
    plan = await _router.route(request)
    fallback = 'local fallback' in (plan.pull_decision.reason or '')
    _store.record_decision(plan, routing_level=1, fallback_used=fallback)
    return plan.model_dump()


@app.post('/v1/chat/completions')
async def openai_compat(req: ChatCompletionsRequest) -> dict:
    """
    Endpoint OpenAI-compatible con cross-node dispatch.
    Flow:
      1. Classifica workload
      2. Se CROSS_NODE_DISPATCH=true, tenta di delegare a un peer remoto
      3. Fallback: esegue localmente su Ollama
    """
    user_request = UserRequest(
        model_alias=req.model,
        messages=req.messages,
    )
    plan = await _router.route(user_request)
    model_id = plan.selected_model_id or settings.default_agent_model

    # Estrai messaggio utente per il dispatcher
    user_msg = next(
        (m.content for m in reversed(req.messages) if m.role == 'user'), ''
    )
    system_msg = next(
        (m.content for m in req.messages if m.role == 'system'), None
    )
    session_id = getattr(req, 'session_id', 'cp-session')

    # --- Cross-node dispatch ---
    if _CROSS_NODE_ENABLED:
        remote_response = await _dispatcher.dispatch(
            session_id=session_id,
            message=user_msg,
            model_alias=req.model,
            system_prompt=system_msg,
            self_node_id=_SELF_NODE_ID,
        )
        if remote_response is not None:
            return {
                'id': 'chatcmpl-hyperspace-remote',
                'object': 'chat.completion',
                'model': req.model,
                'routed_to': 'remote_node',
                'choices': [{
                    'index': 0,
                    'message': {'role': 'assistant', 'content': remote_response},
                    'finish_reason': 'stop',
                }],
                'usage': {},
            }

    # --- Esecuzione locale ---
    hot = await _ensure_model_hot(model_id)
    if not hot:
        logger.warning(f'Pull {model_id} fallito, fallback a {settings.default_agent_model}')
        model_id = settings.default_agent_model

    ollama_payload = {
        'model': model_id,
        'messages': [m.model_dump() for m in req.messages],
        'stream': False,
    }
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f'{_OLLAMA_URL}/api/chat', json=ollama_payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get('message', {}).get('content', '')
            return {
                'id': 'chatcmpl-hyperspace',
                'object': 'chat.completion',
                'model': model_id,
                'routed_to': 'local',
                'choices': [{
                    'index': 0,
                    'message': {'role': 'assistant', 'content': content},
                    'finish_reason': data.get('done_reason', 'stop'),
                }],
                'usage': {
                    'prompt_tokens': data.get('prompt_eval_count', 0),
                    'completion_tokens': data.get('eval_count', 0),
                },
            }
    except httpx.HTTPStatusError as e:
        logger.error(f'Ollama HTTP error: {e}')
        raise HTTPException(
            status_code=502,
            detail=f'Ollama error {e.response.status_code}: modello {model_id} non disponibile.'
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail='Ollama non raggiungibile')


# ------------------------------------------------------------------
# Proxy endpoints -> authority
# ------------------------------------------------------------------

@app.get('/catalog')
async def proxy_catalog() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f'{_AUTHORITY_URL}/catalog')
        return resp.json()


@app.get('/catalog/role/{role}')
async def proxy_catalog_role(role: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f'{_AUTHORITY_URL}/catalog/role/{role}')
        return resp.json()


# ------------------------------------------------------------------
# Proxy endpoints -> worker
# ------------------------------------------------------------------

@app.get('/votes/{memory_id}')
async def proxy_votes(memory_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f'{_WORKER_URL}/votes/{memory_id}')
        return resp.json()


@app.get('/votes/tally/{memory_id}')
async def proxy_tally(memory_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f'{_WORKER_URL}/votes/tally/{memory_id}')
        return resp.json()


@app.post('/replay')
async def proxy_replay(dream_id: str, replay_model_id: str, trigger: str = 'manual') -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f'{_WORKER_URL}/replay',
            params={'dream_id': dream_id, 'replay_model_id': replay_model_id, 'trigger': trigger},
        )
        return resp.json()


@app.get('/stats')
async def get_stats() -> dict:
    return _store.stats()


@app.get('/decisions')
async def recent_decisions(limit: int = 20) -> dict:
    return {'decisions': _store.recent_decisions(limit)}


@app.get('/dispatch/peers')
async def dispatch_peers() -> dict:
    """Debug: mostra i peer alive visti dal dispatcher."""
    peers = await _dispatcher.get_alive_peers()
    return {'cross_node_enabled': _CROSS_NODE_ENABLED, 'alive_peers': peers}


if __name__ == '__main__':
    uvicorn.run(
        'control_plane.server:app',
        host='0.0.0.0',
        port=settings.control_plane_api_port,
        reload=False,
    )
