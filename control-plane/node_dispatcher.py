# HyperSpace-AGI v1.1 - Node Dispatcher
# Interroga authority per peer alive, sceglie il nodo migliore, inoltra la chat
from __future__ import annotations
import logging
import httpx
from shared.settings import settings

logger = logging.getLogger('node_dispatcher')

CLUSTER_SECRET = settings.cluster_secret if hasattr(settings, 'cluster_secret') else ''


class NodeDispatcher:
    """
    Dispatcher cross-nodo v1.1.
    Flow:
      1. Chiede ad authority la lista dei peer alive
      2. Filtra peer con load < MAX_LOAD e modello compatibile
      3. Sceglie il peer con load minore (least-loaded)
      4. Inoltra la richiesta a peer_url/chat con il cluster secret
      5. Se nessun peer disponibile -> ritorna None (fallback locale)
    """

    MAX_LOAD = 0.8

    def __init__(self, authority_url: str | None = None) -> None:
        self.authority_url = authority_url or f'http://authority:{settings.authority_api_port}'

    async def get_alive_peers(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f'{self.authority_url}/peers?alive_only=true')
                if r.status_code == 200:
                    data = r.json()
                    # authority ritorna {"nodes": [...]} o lista diretta
                    nodes = data.get('nodes', data) if isinstance(data, dict) else data
                    return [n for n in nodes if isinstance(n, dict)]
        except Exception as e:
            logger.warning(f'NodeDispatcher: impossibile contattare authority: {e}')
        return []

    def _peer_has_model(self, peer: dict, model_alias: str) -> bool:
        """Controlla se il peer ha il modello richiesto (o accetta 'auto')."""
        if model_alias in ('auto', '', None):
            return True
        models = peer.get('models', [])
        return any(model_alias in m for m in models)

    def _pick_best_peer(self, peers: list[dict], model_alias: str, self_node_id: str) -> dict | None:
        """Sceglie il peer remoto con load minore, escludendo se stesso."""
        candidates = [
            p for p in peers
            if p.get('node_id') != self_node_id
            and p.get('alive', True)
            and p.get('load', 0.0) < self.MAX_LOAD
            and self._peer_has_model(p, model_alias)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.get('load', 0.0))

    async def dispatch(self, session_id: str, message: str,
                       model_alias: str, system_prompt: str | None,
                       self_node_id: str) -> str | None:
        """
        Tenta di delegare la richiesta a un nodo remoto.
        Ritorna la risposta come stringa, o None se nessun peer disponibile.
        """
        peers = await self.get_alive_peers()
        best = self._pick_best_peer(peers, model_alias, self_node_id)
        if best is None:
            logger.debug('NodeDispatcher: nessun peer remoto disponibile, esecuzione locale')
            return None

        host = best.get('host', '')
        port = best.get('port', 8765)
        peer_url = f'http://{host}:{port}'
        nickname = best.get('nickname', best.get('node_id', 'unknown'))
        logger.info(f'NodeDispatcher: delego a {nickname} ({peer_url}) load={best.get("load", 0)}')

        headers = {'X-HyperSpace-Secret': CLUSTER_SECRET} if CLUSTER_SECRET else {}
        payload = {
            'session_id': session_id,
            'message': message,
            'model_alias': model_alias,
        }
        if system_prompt:
            payload['system_prompt'] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f'{peer_url}/chat', json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                response = data.get('response', '')
                logger.info(f'NodeDispatcher: risposta da {nickname} ({len(response)} chars)')
                return response
        except Exception as e:
            logger.warning(f'NodeDispatcher: errore da {nickname}: {e}')
            return None
