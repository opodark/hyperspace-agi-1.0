# HyperSpace-AGI v1.1 - Idle Chat Engine
# Quando un nodo e' idle, avvia conversazioni sintetiche con i peer
# per generare memorie episodiche che alimentano il dream engine.
#
# Protezioni:
#   - flag synthetic=True nel session_id per non triggerare altri idle loop
#   - max MAX_TURNS turni per conversazione
#   - cooldown CHAT_COOLDOWN secondi tra sessioni
#   - si attiva solo se dream engine NON sta gia' sognando
from __future__ import annotations
import asyncio
import logging
import random
import time
import uuid
import httpx
from shared.domain.models import MemoryTier
from node.memory.tiered_store import TieredMemoryStore
from node.runtime.node_state import NodeStateManager

logger = logging.getLogger('idle_chat_engine')

IDLE_THRESHOLD = 180        # secondi idle prima di avviare chat (piu' alto del dream engine)
LOOP_INTERVAL  = 45         # secondi tra check
MAX_TURNS      = 3          # turni per conversazione sintetica
CHAT_COOLDOWN  = 600        # 10 min tra sessioni di chat
SYNTHETIC_PREFIX = 'synthetic-idle-'  # prefisso session_id per evitare loop

# Topic seed se la memoria e' vuota
_FALLBACK_TOPICS = [
    'Cosa sai fare come agente IA?',
    'Quali sono i tuoi punti di forza come modello linguistico?',
    'Come funziona la memoria distribuita in un sistema multi-agente?',
    'Spiega brevemente il concetto di emergenza nei sistemi complessi.',
    'Qual e\' la differenza tra memoria episodica e semantica?',
]


class IdleChatEngine:
    """
    Idle Chat Engine v1.1.
    Quando il nodo e' idle e non sta sognando:
      1. Sceglie un peer alive a random
      2. Genera un topic dalla memoria SEMANTIC locale (o fallback)
      3. Avvia un dialogo sintetico di MAX_TURNS turni
      4. Salva le risposte in memoria EPISODIC con session_id sintetico
      5. Le nuove memorie alimentano il dream engine al prossimo ciclo
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
        self.node_id    = node_id
        self.state      = state_manager
        self.memory     = memory_store
        self.ollama_url = ollama_url.rstrip('/')
        self.model_id   = model_id
        self.peer_urls  = peer_urls or []
        self._running   = False
        self._last_chat = 0.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info(f'[{self.node_id}] Idle Chat Engine avviato')
        asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(LOOP_INTERVAL)
            try:
                await self._tick()
            except Exception as e:
                logger.warning(f'[{self.node_id}] Idle chat tick error: {e}')

    async def _tick(self) -> None:
        self.state._update_state()

        # Non interrompere il dream engine
        if self.state.state == 'dreaming':
            return

        idle_sec = time.time() - self.state._last_request
        if idle_sec < IDLE_THRESHOLD:
            return

        if (time.time() - self._last_chat) < CHAT_COOLDOWN:
            return

        if not self.peer_urls:
            logger.debug(f'[{self.node_id}] Nessun peer configurato per idle chat')
            return

        peer_url = random.choice(self.peer_urls)
        logger.info(f'[{self.node_id}] Idle da {idle_sec:.0f}s — avvio chat sintetica con {peer_url}')
        await self._synthetic_conversation(peer_url)
        self._last_chat = time.time()

    async def _pick_topic(self) -> str:
        """Sceglie un topic dalla memoria SEMANTIC locale, o usa un fallback."""
        try:
            records = await self.memory.list_recent_by_tier(MemoryTier.SEMANTIC, limit=20)
            if records:
                rec = random.choice(records)
                # Usa il contenuto come spunto, non come domanda letterale
                snippet = rec.content[:120].strip()
                return f'Parlami di questo concetto in modo approfondito: "{snippet}"'
        except Exception:
            pass
        return random.choice(_FALLBACK_TOPICS)

    async def _synthetic_conversation(self, peer_url: str) -> None:
        """Esegue una conversazione sintetica con il peer."""
        session_id = f'{SYNTHETIC_PREFIX}{uuid.uuid4().hex[:8]}'
        topic      = await self._pick_topic()
        history: list[dict] = []

        logger.info(f'[{self.node_id}] Topic sintetico: {topic[:80]}...')

        current_message = topic
        saved = 0

        for turn in range(MAX_TURNS):
            # Manda messaggio al peer
            peer_response = await self._ask_peer(peer_url, session_id, current_message)
            if not peer_response:
                logger.warning(f'[{self.node_id}] Peer {peer_url} non ha risposto al turno {turn+1}')
                break

            history.append({'role': 'user',      'content': current_message})
            history.append({'role': 'assistant', 'content': peer_response})

            # Salva in memoria episodica locale
            from shared.domain.models import MemoryRecord
            for role, text in [('user', current_message), ('assistant', peer_response)]:
                await self.memory.add(MemoryRecord(
                    memory_id  = str(uuid.uuid4()),
                    session_id = session_id,
                    role       = role,
                    content    = text,
                    tier       = MemoryTier.EPISODIC,
                    score      = 0.4,  # score basso: dato sintetico, non validato
                ))
                saved += 1

            # Genera follow-up locale per il prossimo turno
            if turn < MAX_TURNS - 1:
                current_message = await self._generate_followup(peer_response, history)
                if not current_message:
                    break

        logger.info(
            f'[{self.node_id}] Chat sintetica completata: {len(history)//2} turni, '
            f'{saved} memorie episodiche salvate (session={session_id})'
        )

    async def _ask_peer(self, peer_url: str, session_id: str, message: str) -> str | None:
        """Invia un messaggio al peer via /chat."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f'{peer_url}/chat',
                    json={
                        'session_id':    session_id,
                        'message':       message,
                        'model_alias':   'auto',
                        'system_prompt': 'Sei un agente HyperSpace-AGI. Rispondi in italiano in modo conciso e informativo.',
                    },
                )
                if resp.status_code == 200:
                    return resp.json().get('response', '')
        except Exception as e:
            logger.debug(f'[{self.node_id}] _ask_peer error: {e}')
        return None

    async def _generate_followup(self, previous_response: str, history: list[dict]) -> str | None:
        """Genera un follow-up usando Ollama locale."""
        history_text = '\n'.join(
            f"{m['role'].upper()}: {m['content'][:150]}" for m in history[-4:]
        )
        prompt = (
            f'Dato questo dialogo:\n{history_text}\n\n'
            f'Genera UNA domanda di approfondimento breve (max 20 parole) in italiano '
            f'che continui la conversazione in modo utile. Solo la domanda, niente altro.'
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f'{self.ollama_url}/api/generate',
                    json={'model': self.model_id, 'prompt': prompt, 'stream': False},
                )
                resp.raise_for_status()
                return resp.json().get('response', '').strip()
        except Exception as e:
            logger.debug(f'[{self.node_id}] _generate_followup error: {e}')
        return None
