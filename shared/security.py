# HyperSpace-AGI v1.0 - Cluster Security
# Middleware FastAPI per validare il shared secret tra nodi.
# In shared/ perche' usato sia da authority che da node.
from __future__ import annotations
import os
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger('security')

CLUSTER_SECRET = os.getenv('HYPERSPACE_CLUSTER_SECRET', '')
SECRET_HEADER  = 'X-HyperSpace-Secret'

# Endpoint protetti — richiedono secret se CLUSTER_SECRET e' impostato
PROTECTED_PREFIXES = [
    '/gossip/',
    '/dreams/',
    '/peers/announce',
]


def _is_protected(path: str) -> bool:
    for prefix in PROTECTED_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class ClusterSecretMiddleware(BaseHTTPMiddleware):
    """
    Se HYPERSPACE_CLUSTER_SECRET e' impostato, verifica che le chiamate
    verso gli endpoint P2P interni portino l'header corretto.
    Endpoint pubblici (health, chat, catalog, memory) sempre accessibili.
    """
    async def dispatch(self, request: Request, call_next):
        if CLUSTER_SECRET and _is_protected(request.url.path):
            token = request.headers.get(SECRET_HEADER, '')
            if token != CLUSTER_SECRET:
                logger.warning(
                    f'Security: accesso negato a {request.url.path} '
                    f'da {request.client.host if request.client else "?"}'
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        'error': 'Invalid cluster secret',
                        'hint': f'Header {SECRET_HEADER} mancante o errato'
                    }
                )
        return await call_next(request)
