"""
VoiceService — manages the real-time voice agent conversation loop over WebSocket.

Phase 8C: Google Cloud TTS primary (~300ms), Gemini TTS fallback (~8s).
  Long sentences are split into shorter chunks before TTS so each chunk
  starts synthesizing in parallel and arrives sooner.

  Timing debug events are emitted at key milestones so latency can be
  observed in the frontend debug panel.

  Preamble: for high-confidence intents a short pre-answer sentence is
  synthesized immediately while the full Gemini response is being generated,
  giving the user audio within ~300ms of sending their message.

  turn_id: every audio_chunk carries the turn_id it belongs to.
    greeting=0, first user turn=1, second=2, ...
  The frontend discards audio_chunks from interrupted/old turns.
"""
import asyncio
import base64
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

# voice_service.py -> services/ -> app/ -> backend/ -> project root -> agent/
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.exceptions import GeminiNotConfiguredError, SessionNotFoundError
from app.repositories.session_repository import session_repository
from app.schemas.session_schema import GeneratedMessage
from app.services.session_service import session_service

from protectme_agent.conversation_agent import ConversationAgent  # noqa: E402
from protectme_agent.fast_path import match_fast_path, wants_arabic, wants_modify  # noqa: E402
from protectme_agent.gemini_client import GeminiClient  # noqa: E402
from protectme_agent.safety.legal_disclaimer import (  # noqa: E402
    DISCLAIMER_HIGH_RISK,
    DISCLAIMER_VOICE_INTRO,
    should_add_high_risk_disclaimer,
)
from protectme_agent.streaming.tts_service import (  # noqa: E402
    synthesize_speech_fast,
    wav_duration_ms,
)

logger = logging.getLogger(__name__)

# ── Sentence chunking ─────────────────────────────────────────────────────────
# Split long sentences at natural voice break points so TTS tasks are shorter,
# start sooner, and audio arrives with lower perceived latency.

_TTS_MAX_CHARS = 110   # target max chars per TTS chunk

# Matches natural break points where a sentence can be split without losing meaning:
#   comma/semicolon followed by space, em/en dash with spaces,
#   or conjunctions (but, and, or, so, because, however, therefore, although, while)
_BREAK_RE = re.compile(
    r",\s+|;\s+|\s+[—–]\s+"
    r"|\s+(?:but|however|and|or|so|because|therefore|although|while)\s+",
    re.IGNORECASE,
)


def _chunk_for_tts(text: str, max_chars: int = _TTS_MAX_CHARS) -> list[str]:
    """
    Recursively split a sentence into short TTS-friendly chunks.
    Splits at natural break points (comma, conjunction, dash).
    Falls back to word-boundary cut when no break point exists.
    Skips fragments shorter than 8 characters.
    """
    text = text.strip()
    if not text or len(text) < 8:
        return []
    if len(text) <= max_chars:
        return [text]

    # Find the LAST good break point within max_chars
    best: Optional[re.Match] = None
    for m in _BREAK_RE.finditer(text):
        if m.start() > max_chars:
            break
        if m.start() > 12:  # avoid an absurdly tiny first chunk
            best = m

    if best:
        left = text[: best.start()].strip().rstrip(",;")
        right = text[best.end() :].strip()
        result: list[str] = []
        if len(left) >= 8:
            result.extend(_chunk_for_tts(left, max_chars))
        if len(right) >= 8:
            result.extend(_chunk_for_tts(right, max_chars))
        if result:
            return result

    # No regex break — split at the last word boundary within max_chars
    cut = text.rfind(" ", 0, max_chars)
    if cut > 12:
        left = text[:cut].strip()
        right = text[cut:].strip()
        result = []
        if len(left) >= 8:
            result.extend(_chunk_for_tts(left, max_chars))
        if len(right) >= 8:
            result.extend(_chunk_for_tts(right, max_chars))
        if result:
            return result

    return [text]  # cannot split reasonably — keep as-is


# ── Preamble ──────────────────────────────────────────────────────────────────
# A short sentence played immediately while Gemini is generating the full answer.
# Conservative: only used for high-confidence, clearly safe intents.
# Must never be misleading.

_PREAMBLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    # generate_message — most unambiguous, checked first
    (
        re.compile(r"\b(write|draft|email|message|whatsapp|letter|send)\b", re.I),
        "I can draft that message for you.",
    ),
    # summarize_risks — check before generic "explain" to avoid false match on
    # "What is the biggest risk?" hitting an explain-clause preamble
    (
        re.compile(r"\b(biggest risk|main risk|top risk|overall risk|overview|summary)\b", re.I),
        "Let me review the main risks.",
    ),
    # explain_clause — only match the verb "explain" or "describe", not "what is"
    (
        re.compile(r"\b(explain|describe)\b", re.I),
        "Let me explain this clause.",
    ),
    # generate_questions
    (
        re.compile(r"\b(questions|what (should|to) ask|ask them)\b", re.I),
        "Here are the key questions to ask.",
    ),
]


def _select_preamble(user_text: str) -> str:
    """Return a safe preamble for the detected intent, or empty string to skip."""
    for pattern, preamble in _PREAMBLE_PATTERNS:
        if pattern.search(user_text):
            return preamble
    return ""


# ── Arabic voice support (Phase 8H) ──────────────────────────────────────────
# If a chunk contains Arabic script, synthesize it with a Google Cloud Arabic
# voice instead of the English Journey voice. The Arabic voice is configurable
# (GOOGLE_CLOUD_TTS_ARABIC_VOICE). If it is left blank, we pass an empty voice
# name so Google Cloud picks a default ar-XA voice, and log a one-time warning.
_ARABIC_CHARS = re.compile(r"[؀-ۿ]")
_arabic_fallback_warned = False


def _voice_for(text: str, default_voice: str) -> tuple[str, str]:
    """Return (voice_name, language_code) appropriate for the chunk's language.

    English → the configured Journey voice. Arabic → the configured Arabic voice,
    or (if none is set) an empty name so Google selects a default ar-XA voice
    (verified to work) — logged once so it's visible the voice wasn't pinned."""
    global _arabic_fallback_warned
    if _ARABIC_CHARS.search(text):
        lang = settings.google_cloud_tts_arabic_language or "ar-XA"
        voice = (settings.google_cloud_tts_arabic_voice or "").strip()
        if voice:
            return voice, lang
        if not _arabic_fallback_warned:
            logger.warning(
                "[Voice] Arabic requested — Arabic TTS voice not configured, using fallback voice"
            )
            _arabic_fallback_warned = True
        return "", lang  # empty name → Google Cloud picks a default ar-XA voice
    return default_voice, settings.google_cloud_tts_language or "en-US"


# ── TTS task ──────────────────────────────────────────────────────────────────


def _build_gemini_client() -> GeminiClient:
    return GeminiClient(
        api_key=settings.gemini_api_key,
        analysis_model=settings.gemini_analysis_model,
        conversation_model=settings.gemini_conversation_model,
        live_model=settings.gemini_live_model,
        voice_fallback_model=settings.voice_fallback_model,
    )


def _build_greeting(session) -> str:
    if not session.risk_report:
        return DISCLAIMER_VOICE_INTRO
    overall = session.risk_report.get("overall_risk", "")
    risk_count = len(session.risk_report.get("risks", []))
    contract_type = session.risk_report.get("contract_type", "your contract")
    greeting = (
        f"I can see you've analyzed {contract_type} with {risk_count} risk(s) "
        f"identified and an overall risk of {overall}. "
        "What would you like to know or do?"
    )
    if should_add_high_risk_disclaimer(overall):
        greeting += f" {DISCLAIMER_HIGH_RISK}"
    return greeting


async def _tts_and_send(
    websocket: WebSocket,
    lock: asyncio.Lock,
    text: str,
    seq: int,
    turn_id: int,
    t_turn_start: float,
    emit_error_event: bool = True,
    google_cloud_api_key: str = "",
    gemini_api_key: str = "",
    voice_name: str = "",
    timeout_seconds: float = 8.0,
) -> None:
    """
    Background task: synthesize one TTS chunk, send audio_chunk over WebSocket.

    Google Cloud TTS Journey voice (~300ms) with Gemini TTS fallback (~8s).
    turn_id lets the frontend discard chunks from interrupted turns.
    emit_error_event=False for greeting (keeps handshake message ordering clean).
    duration_ms carries exact WAV playback length so the frontend can time
    progressive word-by-word text reveal.

    Per-chunk timeout (timeout_seconds): if synthesis stalls, we stop waiting,
    emit a tts_error (the frontend shows that chunk's text instead), and let the
    turn finish — one slow chunk never blocks audio_done for the whole turn.
    """
    from protectme_agent.streaming.tts_service import _GCP_DEFAULT_VOICE  # noqa: E402

    # Pick an Arabic voice automatically when the chunk is Arabic.
    resolved_voice, language_code = _voice_for(text, voice_name or _GCP_DEFAULT_VOICE)

    t_tts_start = time.monotonic()
    timed_out = False
    try:
        wav = await asyncio.wait_for(
            synthesize_speech_fast(
                text,
                google_cloud_api_key=google_cloud_api_key,
                gemini_api_key=gemini_api_key,
                voice_name=resolved_voice,
                language_code=language_code,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        wav = None
        timed_out = True
        logger.warning(
            "TTS chunk timed out after %.1fs — turn=%d seq=%d", timeout_seconds, turn_id, seq
        )
    except Exception as exc:
        wav = None
        logger.warning("TTS chunk failed — turn=%d seq=%d: %s", turn_id, seq, exc)
    tts_ms = int((time.monotonic() - t_tts_start) * 1000)

    try:
        if wav:
            duration_ms = wav_duration_ms(wav)
            audio_b64 = base64.b64encode(wav).decode()
            t_send = time.monotonic() - t_turn_start
            async with lock:
                await websocket.send_json(
                    {
                        "type": "audio_chunk",
                        "turn_id": turn_id,
                        "seq": seq,
                        "text": text,
                        "audio": audio_b64,
                        "mime": "audio/wav",
                        "duration_ms": duration_ms,
                    }
                )
                await websocket.send_json(
                    {
                        "type": "debug",
                        "log": (
                            f"[TTS] turn={turn_id} seq={seq} | "
                            f"tts={tts_ms}ms | dur={duration_ms}ms | t_sent={t_send:.2f}s"
                        ),
                    }
                )
        elif emit_error_event:
            logger.warning(
                "TTS no audio — turn=%d seq=%d%s", turn_id, seq,
                " (timeout)" if timed_out else "",
            )
            async with lock:
                await websocket.send_json(
                    {
                        "type": "tts_error",
                        "turn_id": turn_id,
                        "seq": seq,
                        "text": text,
                        "message": (
                            f"TTS timed out after {timeout_seconds:.0f}s, showing text only"
                            if timed_out else "TTS failed, showing text only"
                        ),
                    }
                )
        else:
            logger.warning("TTS no audio for greeting (suppressed) — seq=%d", seq)
    except Exception as exc:
        logger.warning(
            "Failed to send audio_chunk turn=%d seq=%d: %s", turn_id, seq, exc
        )


# ── Service ───────────────────────────────────────────────────────────────────


class VoiceService:
    """
    Manages the WebSocket conversation loop.
    Phase 8C: fast TTS via Google Cloud TTS + sentence chunking + preamble.
    """

    async def handle_voice_session(
        self, session_id: str, websocket: WebSocket
    ) -> None:
        if not settings.is_gemini_configured:
            raise GeminiNotConfiguredError()

        if not session_repository.exists(session_id):
            raise SessionNotFoundError(session_id)

        session = session_repository.get(session_id)
        client = _build_gemini_client()
        agent = ConversationAgent(client)

        # Shared lock — all concurrent TTS tasks serialise WS writes through this
        send_lock = asyncio.Lock()

        # turn_id: greeting=0, first user turn=1, ...
        _next_turn_id = 1

        # TTS credentials (read once; reused for every task)
        _google_key  = settings.google_cloud_tts_api_key  # legacy REST key (unused)
        _gemini_key  = settings.gemini_api_key
        _voice_name  = settings.google_cloud_tts_voice
        _tts_timeout = settings.tts_chunk_timeout_seconds

        # ── Handshake ──────────────────────────────────────────────────────────
        async with send_lock:
            await websocket.send_json(
                {"type": "status", "state": "idle", "label": "Connected"}
            )
        greeting = _build_greeting(session)
        async with send_lock:
            # Tagged so the frontend shows/speaks the greeting only once per panel
            # session (silent reconnects re-send it; the client de-dupes on this flag).
            await websocket.send_json(
                {"type": "sentence", "text": greeting, "greeting": True}
            )
            await websocket.send_json(
                {"type": "debug", "log": "[Voice] greeting_sent=true"}
            )

        t_greeting_start = time.monotonic()
        _greeting_task = asyncio.create_task(
            _tts_and_send(
                websocket,
                send_lock,
                greeting,
                seq=0,
                turn_id=0,
                t_turn_start=t_greeting_start,
                emit_error_event=False,
                google_cloud_api_key=_google_key,
                gemini_api_key=_gemini_key,
                voice_name=_voice_name,
                timeout_seconds=_tts_timeout,
            )
        )

        # ── Conversation loop ──────────────────────────────────────────────────
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                logger.info("WS client disconnected — session: %s", session_id)
                _greeting_task.cancel()
                break
            except Exception as exc:
                logger.error("WS receive error — session: %s: %s", session_id, exc)
                _greeting_task.cancel()
                break

            msg_type = data.get("type")
            if msg_type not in ("transcript", "text_input"):
                async with send_lock:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": (
                                f"Unknown message type: {msg_type!r}. "
                                "Send 'transcript' or 'text_input'."
                            ),
                        }
                    )
                continue

            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            # Assign turn ID before any async work
            current_turn_id = _next_turn_id
            _next_turn_id += 1
            t_turn_start = time.monotonic()

            async with send_lock:
                await websocket.send_json(
                    {
                        "type": "debug",
                        "log": f"[TTS] turn={current_turn_id} started",
                    }
                )

            # Refresh session (REST endpoints may have mutated active clause)
            session = session_repository.get(session_id)

            session_service.add_conversation_turn(
                session_id, role="user", content=user_text
            )

            last_tool_result: dict = {}
            assistant_parts: list[str] = []
            tts_tasks: list[asyncio.Task] = []
            seq = 0
            t_first_sentence: Optional[float] = None

            # ── Preamble ───────────────────────────────────────────────────────
            # Short pre-answer played immediately while the answer is produced.
            # Fast-path questions get an intent-specific preamble (or none, since
            # their answer is instant); genuinely complex questions that fall
            # through to Gemini get a neutral "Let me check that." so the user
            # hears something while the model thinks.
            # Arabic turns get an Arabic preamble (never an English one) so the
            # spoken answer stays entirely in Arabic. It's synthesized with the
            # Arabic voice automatically (it contains Arabic script).
            if wants_arabic(user_text):
                preamble = "لحظة من فضلك."  # "one moment, please"
            else:
                preamble = _select_preamble(user_text)
                # Default "Let me check that." only for genuine Gemini-fallback questions —
                # not for fast-path answers, and not for "make it shorter" style draft edits
                # (the modify handler speaks its own confirmation).
                if not preamble and not match_fast_path(user_text) and not wants_modify(user_text):
                    preamble = "Let me check that."
            if preamble:
                async with send_lock:
                    await websocket.send_json({"type": "sentence", "text": preamble})
                assistant_parts.append(preamble)
                chunks = _chunk_for_tts(preamble)
                for chunk in chunks:
                    task = asyncio.create_task(
                        _tts_and_send(
                            websocket,
                            send_lock,
                            chunk,
                            seq=seq,
                            turn_id=current_turn_id,
                            t_turn_start=t_turn_start,
                            emit_error_event=True,
                            google_cloud_api_key=_google_key,
                            gemini_api_key=_gemini_key,
                            voice_name=_voice_name,
                            timeout_seconds=_tts_timeout,
                        )
                    )
                    tts_tasks.append(task)
                    seq += 1
                t_first_sentence = time.monotonic() - t_turn_start
                async with send_lock:
                    await websocket.send_json(
                        {
                            "type": "debug",
                            "log": (
                                f"[TTS] turn={current_turn_id} "
                                f"preamble sent at {t_first_sentence:.2f}s"
                            ),
                        }
                    )

            # ── Agent turn ─────────────────────────────────────────────────────
            try:
                async for event in agent.handle_turn(user_text, session):
                    async with send_lock:
                        await websocket.send_json(event)

                    if (
                        event.get("type") == "tool_result"
                        and event.get("tool") == "generate_message"
                    ):
                        last_tool_result = event.get("result", {})

                    if event.get("type") == "sentence":
                        sentence_text = event["text"]
                        assistant_parts.append(sentence_text)

                        # Track first sentence timing
                        if t_first_sentence is None:
                            t_first_sentence = time.monotonic() - t_turn_start
                            async with send_lock:
                                await websocket.send_json(
                                    {
                                        "type": "debug",
                                        "log": (
                                            f"[TTS] turn={current_turn_id} "
                                            f"first sentence at {t_first_sentence:.2f}s"
                                        ),
                                    }
                                )

                        # Split long sentences into shorter TTS chunks
                        chunks = _chunk_for_tts(sentence_text)
                        for chunk in chunks:
                            task = asyncio.create_task(
                                _tts_and_send(
                                    websocket,
                                    send_lock,
                                    chunk,
                                    seq=seq,
                                    turn_id=current_turn_id,
                                    t_turn_start=t_turn_start,
                                    emit_error_event=True,
                                    google_cloud_api_key=_google_key,
                                    gemini_api_key=_gemini_key,
                                    voice_name=_voice_name,
                                    timeout_seconds=_tts_timeout,
                                )
                            )
                            tts_tasks.append(task)
                            seq += 1

                    if event.get("type") == "draft_ready":
                        generated = GeneratedMessage(
                            clause_ids=last_tool_result.get(
                                "clause_ids", event.get("clause_ids", [])
                            ),
                            message_type=last_tool_result.get(
                                "message_type", "clarification"
                            ),
                            tone=last_tool_result.get("tone", "professional"),
                            format=last_tool_result.get("format", "email"),
                            draft=event.get("draft", ""),
                        )
                        session_service.add_generated_message(session_id, generated)

            except WebSocketDisconnect:
                logger.info("WS disconnected mid-turn — session: %s", session_id)
                for t in tts_tasks:
                    t.cancel()
                return
            except Exception as exc:
                logger.error("Agent error — session: %s: %s", session_id, exc)
                for t in tts_tasks:
                    t.cancel()
                try:
                    async with send_lock:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "An error occurred. Please try again.",
                            }
                        )
                        await websocket.send_json(
                            {"type": "status", "state": "idle", "label": "Ready"}
                        )
                except Exception:
                    return

            # Wait for all TTS tasks, then signal frontend
            if tts_tasks:
                await asyncio.gather(*tts_tasks, return_exceptions=True)

            t_done = time.monotonic() - t_turn_start
            try:
                async with send_lock:
                    await websocket.send_json({"type": "audio_done", "turn_id": current_turn_id})
                    await websocket.send_json(
                        {
                            "type": "debug",
                            "log": (
                                f"[TTS] turn={current_turn_id} done | "
                                f"chunks={seq} | t_total={t_done:.2f}s"
                            ),
                        }
                    )
            except Exception:
                pass

            if assistant_parts:
                session_service.add_conversation_turn(
                    session_id,
                    role="assistant",
                    content=" ".join(assistant_parts),
                )


voice_service = VoiceService()
