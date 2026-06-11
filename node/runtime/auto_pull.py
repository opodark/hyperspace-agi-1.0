# HyperSpace-AGI v1.0 - AutoPull
# Strategia: UN solo modello per ruolo (il migliore che entra nella RAM).
# Evita di scaricare tutto il catalogo e riempire il disco.
from __future__ import annotations
import logging
import os
import httpx

logger = logging.getLogger('auto_pull')

OLLAMA_URL  = os.getenv('OLLAMA_BASE_URL', 'http://ollama:11434')
NODE_RAM_GB = float(os.getenv('NODE_RAM_GB', '0'))
AUTHORITY   = os.getenv('AUTHORITY_URL', 'http://authority:8766')

TARGET_ROLES           = ['small', 'agent', 'coder', 'reasoner']
LARGE_RAM_THRESHOLD_GB = 24.0
TARGET_ROLES_LARGE     = ['reasoner_large', 'agent_large']  # solo su nodi 24GB+


async def get_installed_models() -> set[str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f'{OLLAMA_URL}/api/tags')
            if r.status_code == 200:
                return {m['name'] for m in r.json().get('models', [])}
    except Exception as e:
        logger.warning(f'AutoPull: impossibile leggere modelli installati: {e}')
    return set()


async def pull_model(tag: str) -> bool:
    logger.info(f'AutoPull: inizio pull {tag}')
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            async with client.stream(
                'POST', f'{OLLAMA_URL}/api/pull', json={'name': tag}
            ) as resp:
                async for line in resp.aiter_lines():
                    if '"status":"success"' in line:
                        logger.info(f'AutoPull: {tag} completato ✅')
                        return True
        return False
    except Exception as e:
        logger.error(f'AutoPull: errore pull {tag}: {e}')
        return False


async def _best_for_role(role: str, ram_gb: float) -> dict | None:
    """Chiede ad Authority il miglior modello per ruolo + RAM."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f'{AUTHORITY}/catalog/best/{role}/{ram_gb}')
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        logger.warning(f'AutoPull: errore catalog best/{role}: {e}')
    return None


async def run_auto_pull() -> dict:
    """
    Scarica esattamente 1 modello per ruolo (best-per-role).

    Logica:
    - Per ogni ruolo chiede a Authority il miglior modello che entra nella RAM
      disponibile (con margine 15%).
    - Su nodi con RAM >= 24GB aggiunge anche i ruoli large.
    - Salta i modelli gia' installati.
    - Pull sequenziale: un modello alla volta per non saturare disco e banda.
    """
    if NODE_RAM_GB <= 0:
        return {'status': 'skipped', 'reason': 'NODE_RAM_GB not set'}

    roles = list(TARGET_ROLES)
    if NODE_RAM_GB >= LARGE_RAM_THRESHOLD_GB:
        roles += TARGET_ROLES_LARGE

    logger.info(
        f'AutoPull: {os.getenv("NODE_ID", "?")} — '
        f'RAM={NODE_RAM_GB}GB — ruoli: {roles}'
    )

    installed = await get_installed_models()
    to_pull: list[dict] = []
    skipped_roles: list[str] = []

    for role in roles:
        best = await _best_for_role(role, NODE_RAM_GB)
        if not best:
            skipped_roles.append(role)
            logger.info(f'AutoPull: nessun modello per ruolo={role} con {NODE_RAM_GB}GB, skip')
            continue
        tag = best['ollama_tag']
        if tag in installed:
            logger.info(f'AutoPull: {tag} ({role}) gia installato ✅')
        else:
            to_pull.append({'role': role, 'ollama_tag': tag,
                            'ram_required_gb': best.get('ram_required_gb', '?')})

    if not to_pull:
        return {
            'status':            'ok',
            'pulled':            [],
            'failed':            [],
            'already_installed': sorted(installed),
            'skipped_roles':     skipped_roles,
        }

    logger.info(
        f'AutoPull: {len(to_pull)} da scaricare: '
        f'{[(m["role"], m["ollama_tag"]) for m in to_pull]}'
    )

    pulled, failed = [], []
    for m in to_pull:   # sequenziale: un modello alla volta
        ok = await pull_model(m['ollama_tag'])
        (pulled if ok else failed).append(m['ollama_tag'])

    return {
        'status':            'ok',
        'ram_gb':            NODE_RAM_GB,
        'roles_target':      roles,
        'pulled':            pulled,
        'failed':            failed,
        'skipped_roles':     skipped_roles,
        'already_installed': sorted(installed),
    }
