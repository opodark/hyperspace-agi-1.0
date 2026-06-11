# HyperSpace-AGI v6.1 - Dashboard Server con Authority section
# CONTAINER_SUFFIX env var permette di adattare i nomi container (es. -ext per nodi esterni)
from __future__ import annotations
import asyncio
import docker
import httpx
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import os

app = FastAPI(title='HyperSpace Dashboard', version='2.1.0')
templates = Jinja2Templates(directory='/dashboard/templates')

DOCKER_CLIENT   = docker.from_env()
OLLAMA_URL      = os.getenv('OLLAMA_BASE_URL', 'http://ollama:11434')
CONTROL_PLANE   = os.getenv('CONTROL_PLANE_URL', 'http://control-plane:8768')
AUTHORITY_URL   = os.getenv('AUTHORITY_URL', 'http://authority:8766')
CONTAINER_SUFFIX = os.getenv('CONTAINER_SUFFIX', '')  # es. '-ext' per nodi esterni

NODE_URLS = [
    url.strip()
    for url in os.getenv('NODE_URLS', 'http://node:8765').split(',')
    if url.strip()
]

_BASE_SERVICES = [
    {'base': 'hyperspace-ollama',        'label': 'Ollama',        'port': 11434, 'emoji': '🦙'},
    {'base': 'hyperspace-authority',     'label': 'Authority',     'port': 8766,  'emoji': '🔍'},
    {'base': 'hyperspace-node',          'label': 'Node',          'port': 8765,  'emoji': '🤖'},
    {'base': 'hyperspace-node-b',        'label': 'Node B',        'port': 8770,  'emoji': '🤖'},
    {'base': 'hyperspace-worker',        'label': 'Worker',        'port': 8767,  'emoji': '⚙️'},
    {'base': 'hyperspace-control-plane', 'label': 'Control Plane', 'port': 8768,  'emoji': '🧠'},
    {'base': 'hyperspace-webui',         'label': 'Open WebUI',    'port': 8080,  'emoji': '🌐'},
    {'base': 'hyperspace-dashboard',     'label': 'Dashboard',     'port': 8769,  'emoji': '📊'},
]

# Applica il suffisso ai nomi container
SERVICES = [
    {**s, 'name': f"{s['base']}{CONTAINER_SUFFIX}"}
    for s in _BASE_SERVICES
]


def get_container_status(name: str) -> dict:
    try:
        c = DOCKER_CLIENT.containers.get(name)
        health = c.attrs.get('State', {}).get('Health', {})
        return {'status': c.status, 'health': health.get('Status', 'none') if health else 'none',
                'running': c.status == 'running'}
    except Exception:
        return {'status': 'not found', 'health': 'none', 'running': False}


async def get_ollama_models() -> list:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f'{OLLAMA_URL}/api/tags')
            return r.json().get('models', [])
    except Exception:
        return []


async def get_routing_stats() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f'{CONTROL_PLANE}/stats')
            return r.json()
    except Exception:
        return {}


async def get_node_dreams(url: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f'{url}/dreams')
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def get_all_peers() -> list[dict]:
    seen: dict[str, dict] = {}

    async def fetch_one(url: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f'{url}/gossip/peers')
                if r.status_code != 200:
                    return
                data = r.json()
                for p in [data['self']] + data.get('peers', []):
                    nid = p.get('node_id', '')
                    if not nid or nid.startswith('__bootstrap'):
                        continue
                    if p.get('last_seen', 0) > seen.get(nid, {}).get('last_seen', 0):
                        seen[nid] = p
        except Exception:
            pass

    await asyncio.gather(*[fetch_one(url) for url in NODE_URLS])
    return sorted(seen.values(), key=lambda p: (not p.get('alive', False), p.get('node_id', '')))


async def get_authority_data() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            peers_r, catalog_r = await asyncio.gather(
                client.get(f'{AUTHORITY_URL}/peers?alive_only=false'),
                client.get(f'{AUTHORITY_URL}/catalog'),
            )
            registry = peers_r.json() if peers_r.status_code == 200 else {'total': 0, 'alive': 0, 'nodes': []}
            catalog  = catalog_r.json().get('models', []) if catalog_r.status_code == 200 else []
            return {'registry': registry, 'catalog': catalog}
    except Exception:
        return {'registry': {'total': 0, 'alive': 0, 'nodes': []}, 'catalog': []}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    services = [{**svc, **get_container_status(svc['name'])} for svc in SERVICES]
    models, stats, dream_results, peers, auth_data = await asyncio.gather(
        get_ollama_models(),
        get_routing_stats(),
        asyncio.gather(*[get_node_dreams(url) for url in NODE_URLS]),
        get_all_peers(),
        get_authority_data(),
    )
    dream_nodes = [d for d in dream_results if d is not None]
    return templates.TemplateResponse('index.html', {
        'request': request, 'services': services, 'models': models,
        'stats': stats, 'dream_nodes': dream_nodes, 'peers': peers,
        'registry': auth_data['registry'], 'catalog': auth_data['catalog'],
    })


@app.get('/partials/status', response_class=HTMLResponse)
async def partial_status(request: Request):
    services = [{**svc, **get_container_status(svc['name'])} for svc in SERVICES]
    return templates.TemplateResponse('partials/status.html', {'request': request, 'services': services})


@app.get('/partials/models', response_class=HTMLResponse)
async def partial_models(request: Request):
    models = await get_ollama_models()
    return templates.TemplateResponse('partials/models.html', {'request': request, 'models': models})


@app.get('/partials/stats', response_class=HTMLResponse)
async def partial_stats(request: Request):
    stats = await get_routing_stats()
    return templates.TemplateResponse('partials/stats.html', {'request': request, 'stats': stats})


@app.get('/partials/dreams', response_class=HTMLResponse)
async def partial_dreams(request: Request):
    results = await asyncio.gather(*[get_node_dreams(url) for url in NODE_URLS])
    dream_nodes = [d for d in results if d is not None]
    return templates.TemplateResponse('partials/dreams.html', {'request': request, 'nodes': dream_nodes})


@app.get('/partials/peers', response_class=HTMLResponse)
async def partial_peers(request: Request):
    peers = await get_all_peers()
    return templates.TemplateResponse('partials/peers.html', {'request': request, 'peers': peers})


@app.get('/partials/authority', response_class=HTMLResponse)
async def partial_authority(request: Request):
    auth_data = await get_authority_data()
    return templates.TemplateResponse('partials/authority.html', {
        'request': request,
        'registry': auth_data['registry'],
        'catalog':  auth_data['catalog'],
    })


@app.post('/container/{name}/restart')
async def restart_container(name: str):
    try:
        DOCKER_CLIENT.containers.get(name).restart(timeout=10)
        return HTMLResponse(f'<span class="text-green-400">✓ {name} riavviato</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="text-red-400">✗ {e}</span>')


@app.post('/container/{name}/stop')
async def stop_container(name: str):
    try:
        DOCKER_CLIENT.containers.get(name).stop(timeout=10)
        return HTMLResponse(f'<span class="text-yellow-400">⏹ {name} fermato</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="text-red-400">✗ {e}</span>')


@app.post('/container/{name}/start')
async def start_container(name: str):
    try:
        DOCKER_CLIENT.containers.get(name).start()
        return HTMLResponse(f'<span class="text-green-400">▶ {name} avviato</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="text-red-400">✗ {e}</span>')


@app.get('/logs/{name}')
async def get_logs(name: str, lines: int = 100):
    try:
        c    = DOCKER_CLIENT.containers.get(name)
        logs = c.logs(tail=lines, timestamps=True).decode('utf-8', errors='replace')
        return HTMLResponse(f'<pre class="text-xs text-green-300 whitespace-pre-wrap font-mono">{logs}</pre>')
    except Exception as e:
        return HTMLResponse(f'<pre class="text-red-400">{e}</pre>')


@app.post('/ollama/pull')
async def pull_model(request: Request):
    form  = await request.form()
    model = form.get('model', '').strip()
    if not model:
        return HTMLResponse('<span class="text-red-400">Specifica un modello</span>')

    async def stream_pull():
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream('POST', f'{OLLAMA_URL}/api/pull',
                                         json={'name': model}) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data   = json.loads(line)
                            status = data.get('status', '')
                            tot    = data.get('total', 0)
                            comp   = data.get('completed', 0)
                            if tot > 0:
                                pct    = int(comp * 100 / tot)
                                bar    = '█' * (pct // 5) + '░' * (20 - pct // 5)
                                msg    = f'[{bar}] {pct}% ({comp // 1_048_576}/{tot // 1_048_576} MB)'
                            else:
                                msg = status
                            yield f'data: <div class="font-mono text-xs text-green-300">{msg}</div>\n\n'
                            if status == 'success':
                                yield 'data: <div class="text-green-400 font-bold">✓ Pull completato!</div>\n\n'
                                return
                        except Exception:
                            pass
        except Exception as e:
            yield f'data: <div class="text-red-400">Errore: {e}</div>\n\n'

    return StreamingResponse(stream_pull(), media_type='text/event-stream')


@app.delete('/ollama/model/{name:path}')
async def delete_model(name: str):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # httpx.delete() non supporta json= — usiamo request() esplicitamente
            r = await client.request(
                'DELETE',
                f'{OLLAMA_URL}/api/delete',
                json={'name': name},
            )
            if r.status_code == 200:
                return HTMLResponse(f'<span class="text-green-400">✓ {name} eliminato</span>')
            return HTMLResponse(f'<span class="text-red-400">Errore {r.status_code}: {r.text}</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="text-red-400">{e}</span>')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('server:app', host='0.0.0.0', port=8769, reload=False)
