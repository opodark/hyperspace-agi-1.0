# HyperSpace-AGI v1.1 - Dream Engine
# Background task che si attiva dopo IDLE_THRESHOLD secondi di inattivita'.
# Flow: legge memorie episodiche -> genera dream via Ollama -> propaga ai peer -> promuove a SEMANTIC
from __future__ import annotations
import asyncio
import logging
import time
import uuid
import httpx
from shared.domain.models import MemoryTier, MemoryRecord
from node.memory.tiered_store import TieredMemoryStore
from node.runtime.node_state import NodeStateManager, DreamEntry

logger = logging.getLogger('dream_engine')

# Quante memorie episodiche usare come contesto per generare il dream
CONTEXT_LIMIT   = 8
# Soglia score minima perche' un dream venga auto-promosso a SEMANTIC
PROMOTE_THRESH  = 0.65
# Secondi di inattivita' prima di entrare in dreaming
IDLE_THRESHOLD  = 120
# Intervallo del loop di controllo (secondi)
LOOP_INTERVAL   = 30
# Max dream generati per sessione di dreaming
MAX_DREAMS_BATCH = 3

_DREAM_PROMPT = """
Sei un agente IA in fase di consolidamento della memoria (dreaming).
Analizza le seguenti interazioni recenti e genera UNA singola intuizione sintetica
che potrebbe essere utile in futuro. Sii conciso (max 3 frasi).
Non usare elenchi puntati. Scrivi in italiano.

Memorie recenti:
{memories}

Intuzione sintetica:"""


class DreamEngine:
    """
    Dream Engine v1.1.
    - Si attiva quando il nodo e' in stato 'sleeping' (idle > IDLE_THRESHOLD)
    - Legge le ultime N memorie EPISODIC dal TieredMemoryStore
    - Chiama Ollama per generare una sintesi (dream)
    - Crea un DreamEntry e lo propaga ai peer via gossip
    - Se score > PROMOTE_THRESH, promuove direttamente a memoria SEMANTIC
    """

    def __init__(
        self,
        node_id: str,
        state_manager: NodeStateManager,
        memory_store: TieredMemoryStore,
        ollama_url: str,
        model_id: str,
        peer_urls: list[str] | None = None,
    ) -> None:
        self.node_id       = node_id
        self.state         = state_manager
        self.memory        = memory_store
        self.ollama_url    = ollama_url.rstrip('/')
        self.model_id      = model_id
        self.peer_urls     = peer_urls or []
        self._running      = False
        self._last_dream   = 0.0   # timestamp ultimo dream generato
        self._dream_cooldown = 300  # 5 min tra una sessione e l'altra

    async def start(self) -> None:
        """Avvia il loop in background."""
        if self._running:
            return
        self._running = True
        logger.info(f'[{self.node_id}] Dream Engine avviato (idle_threshold={IDLE_THRESHOLD}s)')
        asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(LOOP_INTERVAL)
            try:
                await self._tick()
            except Exception as e:
                logger.warning(f'[{self.node_id}] Dream engine tick error: {e}')

    async def _tick(self) -> None:
        self.state._update_state()
        if self.state.state not in ('sleeping', 'active'):
            return

        idle_sec = time.time() - self.state._last_request
        if idle_sec < IDLE_THRESHOLD:
            return

        cooldown_ok = (time.time() - self._last_dream) > self._dream_cooldown
        if not cooldown_ok:
            return

        logger.info(f'[{self.node_id}] Nodo idle da {idle_sec:.0f}s — avvio dreaming...')
        self.state.state = 'dreaming'
        await self._dreaming_session()
        self.state._update_state()

    async def _dreaming_session(self) -> None:
        """Genera MAX_DREAMS_BATCH dream da memorie episodiche recenti."""
        # Prendi le ultime memorie episodiche (global, tutte le sessioni)
        records = await self.memory.list_recent_by_tier(
            MemoryTier.EPISODIC, limit=CONTEXT_LIMIT * MAX_DREAMS_BATCH
        )
        if len(records) < 2:
            logger.info(f'[{self.node_id}] Memorie insufficienti per sognare ({len(records)})')
            return

        # Suddividi in batch da CONTEXT_LIMIT
        batches = [
            records[i:i + CONTEXT_LIMIT]
            for i in range(0, min(len(records), CONTEXT_LIMIT * MAX_DREAMS_BATCH), CONTEXT_LIMIT)
        ][:MAX_DREAMS_BATCH]

        generated = 0
        for batch in batches:
            dream_content = await self._generate_dream(batch)
            if not dream_content:
                continue
            score = self._score_dream(dream_content, batch)
            dream = DreamEntry(
                dream_id    = f'dream-{self.node_id}-{uuid.uuid4().hex[:8]}',
                content     = dream_content,
                score       = score,
                origin_node = self.node_id,
            )
            self.state.add_dream(dream)
            logger.info(f'[{self.node_id}] Dream generato: score={score:.2f} — {dream_content[:60]}...')

            # Promuovi a SEMANTIC se score alto
            if score >= PROMOTE_THRESH:
                await self._promote_to_memory(dream)

            # Propaga ai peer
            await self._propagate(dream)
            generated += 1

        self._last_dream = time.time()
        logger.info(f'[{self.node_id}] Sessione dreaming completata: {generated} dream generati')

    async def _generate_dream(self, records: list[MemoryRecord]) -> str | None:
        """Chiama Ollama per generare una sintesi dai record di memoria."""
        memories_text = '\n'.join(
            f'- [{r.role}]: {r.content[:200]}' for r in records
        )
        prompt = _DREAM_PROMPT.format(memories=memories_text)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f'{self.ollama_url}/api/generate',
                    json={'model': self.model_id, 'prompt': prompt, 'stream': False},
                )
                resp.raise_for_status()
                return resp.json().get('response', '').strip()
        except Exception as e:
            logger.warning(f'[{self.node_id}] Ollama dream generation error: {e}')
            return None

    def _score_dream(self, content: str, source_records: list[MemoryRecord]) -> float:
        """Calcola score base: lunghezza normalizzata + score medio delle memorie sorgente."""
        length_score  = min(len(content) / 400, 1.0)  # 400 chars = score massimo
        memory_score  = sum(r.score for r in source_records) / max(len(source_records), 1)
        # Penalizza contenuti troppo corti (<30 chars) o con errori evidenti
        if len(content) < 30:
            return 0.1
        return round((length_score * 0.4 + memory_score * 0.6), 3)

    async def _promote_to_memory(self, dream: DreamEntry) -> None:
        """Promuove il dream a memoria SEMANTIC nel TieredMemoryStore."""
        try:
            record = MemoryRecord(
                memory_id         = dream.dream_id,
                session_id        = f'dream-session-{self.node_id}',
                role              = 'assistant',
                content           = dream.content,
                tier              = MemoryTier.SEMANTIC,
                score             = dream.score,
                source_task_id    = None,
                validation_status = 'dream_promoted',
                validation_notes  = f'Auto-promoted by dream engine (score={dream.score:.3f})',
            )
            await self.memory.add(record)
            logger.info(f'[{self.node_id}] Dream {dream.dream_id} promosso a SEMANTIC')
        except Exception as e:
            logger.warning(f'[{self.node_id}] Promozione dream fallita: {e}')

    async def _propagate(self, dream: DreamEntry) -> None:
        """Invia il dream ai peer via /dreams/receive."""
        if not self.peer_urls:
            return
        payload = dream.to_dict()
        payload['content'] = dream.content  # to_dict() tronca, ripristina full

        async def send_one(url: str) -> None:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(f'{url}/dreams/receive', json=payload)
                    if r.status_code == 200:
                        logger.debug(f'[{self.node_id}] Dream propagato a {url}')
            except Exception as e:
                logger.debug(f'[{self.node_id}] Propagazione fallita verso {url}: {e}')

        await asyncio.gather(*[send_one(u) for u in self.peer_urls])
