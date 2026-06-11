# HyperSpace-AGI v1.0 - Authority Server
from __future__ import annotations
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from shared.domain.models import RoutingContext
from shared.settings import settings
from shared.security import ClusterSecretMiddleware, CLUSTER_SECRET
from authority.model_catalog import (
    get_catalog, get_by_role, get_by_id,
    get_models_for_ram, get_best_model_for_role_and_ram
)
from authority.policy_engine import policy_engine
from authority.node_registry import node_registry

logger = logging.getLogger('authority')


@asynccontextmanager
async def lifespan(app: FastAPI):
    if CLUSTER_SECRET:
        logger.info('Authority: cluster secret attivo 🔒')
    else:
        logger.warning('Authority: HYPERSPACE_CLUSTER_SECRET non impostato — rete aperta')
    await node_registry.start_cleanup()
    yield
    await node_registry.stop_cleanup()


app = FastAPI(
    title='HyperSpace-AGI Authority',
    description='Policy Engine + Model Catalog + NodeRegistry',
    version='1.0.0',
    lifespan=lifespan,
)

app.add_middleware(ClusterSecretMiddleware)


@app.get('/health')
async def health() -> dict:
    alive = node_registry.get_all(alive_only=True)
    return {
        'status': 'ok', 'service': 'authority', 'version': '1.0.0',
        'nodes_alive': len(alive),
        'cluster_secret_active': bool(CLUSTER_SECRET),
    }


# ── NodeRegistry ────────────────────────────────────────────────────────────────

@app.post('/peers/announce')
async def announce_peer(data: dict) -> dict:
    try:
        entry  = node_registry.announce(data)
        peers  = node_registry.get_all(alive_only=True)
        others = [p.to_dict() for p in peers if p.node_id != entry.node_id]
        return {'status': 'registered', 'node_id': entry.node_id, 'peers': others, 'total': len(others)}
    except ValueError as e:
        return JSONResponse(status_code=400, content={'error': str(e)})


@app.get('/peers')
async def list_peers(alive_only: bool = True) -> dict:
    nodes = node_registry.get_all(alive_only=alive_only)
    return {
        'total': len(nodes),
        'alive': sum(1 for n in nodes if n.is_alive()),
        'nodes': [n.to_dict() for n in nodes],
    }


@app.get('/peers/{node_id}')
async def get_peer(node_id: str) -> dict:
    entry = node_registry.get(node_id)
    if not entry:
        return JSONResponse(status_code=404, content={'error': f'node not found: {node_id}'})
    return entry.to_dict()


@app.delete('/peers/{node_id}')
async def remove_peer(node_id: str) -> dict:
    if not node_registry.remove(node_id):
        return JSONResponse(status_code=404, content={'error': f'node not found: {node_id}'})
    return {'status': 'removed', 'node_id': node_id}


# ── Model Catalog ────────────────────────────────────────────────────────────────

@app.get('/catalog')
async def list_catalog() -> dict:
    catalog = get_catalog()
    return {
        'total': len(catalog),
        'models': [{
            'model_id': e.profile.model_id, 'ollama_tag': e.ollama_tag,
            'role': e.role, 'priority': e.priority,
            'size_class': e.profile.size_class,
            'ram_required_gb': e.profile.ram_required_gb,
            'is_available': e.is_available,
        } for e in catalog],
    }


@app.get('/catalog/ram/{ram_gb}')
async def catalog_for_ram(ram_gb: float) -> dict:
    models = get_models_for_ram(ram_gb)
    return {
        'ram_gb':      ram_gb,
        'usable_ram':  round(ram_gb * 0.85, 1),
        'total':       len(models),
        'models': [{
            'model_id':        e.profile.model_id,
            'ollama_tag':      e.ollama_tag,
            'role':            e.role,
            'ram_required_gb': e.profile.ram_required_gb,
            'reasoning_score': e.profile.reasoning_score,
            'priority':        e.priority,
        } for e in models],
    }


@app.get('/catalog/best/{role}/{ram_gb}')
async def best_for_role(role: str, ram_gb: float) -> dict:
    entry = get_best_model_for_role_and_ram(role, ram_gb)
    if not entry:
        return JSONResponse(status_code=404,
                            content={'error': f'no model for role={role} ram={ram_gb}GB'})
    return {
        'role': role, 'ram_gb': ram_gb,
        'model_id':        entry.profile.model_id,
        'ollama_tag':      entry.ollama_tag,
        'ram_required_gb': entry.profile.ram_required_gb,
    }


@app.get('/catalog/role/{role}')
async def list_by_role(role: str) -> dict:
    entries = get_by_role(role)
    if not entries:
        return JSONResponse(status_code=404, content={'error': f'no models for role: {role}'})
    return {'role': role, 'models': [e.model_dump() for e in entries]}


@app.get('/catalog/{model_id}')
async def get_model(model_id: str) -> dict:
    entry = get_by_id(model_id)
    if not entry:
        return JSONResponse(status_code=404, content={'error': f'model not found: {model_id}'})
    return entry.model_dump()


@app.post('/resolve')
async def resolve_routing(ctx: RoutingContext) -> dict:
    plan = policy_engine.resolve(ctx)
    return plan.model_dump()


if __name__ == '__main__':
    uvicorn.run('authority.server:app', host='0.0.0.0',
                port=settings.authority_api_port, reload=False)
