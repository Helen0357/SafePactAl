"""
LiveVoiceService — Phase 8E: Full Gemini Live audio-in / audio-out.

Architecture (bidirectional streaming):

  Browser mic → PCM base64 JSON → /ws/live/{session_id}
                ↕  two concurrent asyncio tasks  ↕
         Gemini Live session (persistent, stateful)
                ↕
  Browser playback ← WAV base64 JSON ← audio_chunk events

Task 1 — _ws_to_live:
  Reads audio_input / text_input frames from the browser WebSocket.
  Forwards raw PCM to Gemini Live via send_realtime_input().
  Forwards text via send_client_content() (text-box fallback).

Task 2 — _live_to_ws:
  Reads Gemini Live responses via live_session.receive().
  Buffers PCM output into 300ms WAV chunks, sends audio_chunk events.
  Extracts transcript text from Gemini 2.5 Flash's side-channel text output
  and sends sentence events (drives the live-caption word reveal).
  Detects draft/write intent in model text → hybrid: generates a proper
  message draft with the conversation model and emits draft_ready.

Task shutdown: asyncio.wait(FIRST_COMPLETED) → cancel the remaining task.

Interruption: browser simply starts streaming new audio while the model is
mid-response; Gemini Live's built-in VAD stops the current response automatically.

Zero disk I/O — all audio stays in RAM.
"""
import asyncio
import base64
import io
import logging
import re
import sys
import time
import wave
from pathlib import Path
from typing import Optional

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.exceptions import GeminiNotConfiguredError, SessionNotFoundError
from app.repositories.session_repository import session_repository

logger = logging.getLogger(__name__)

# ── Audio constants ───────────────────────────────────────────────────────────
_IN_SAMPLE_RATE   = 16_000   
_OUT_SAMPLE_RATE  = 24_000  
_OUT_CHANNELS     = 1
_OUT_SAMPLE_WIDTH = 2       

_PCM_CHUNK_BYTES  = _OUT_SAMPLE_RATE * _OUT_SAMPLE_WIDTH * _OUT_CHANNELS * 300 // 1000

_LIVE_MODEL_DEFAULT = "gemini-2.5-flash-native-audio-latest"
_LIVE_VOICE         = "Charon"

_IN_MIME = f"audio/pcm;rate={_IN_SAMPLE_RATE}"

_DRAFT_RE = re.compile(
    r"\b(draft|write|compose|prepare|create)\b",
    re.IGNORECASE,
)


# ── Audio helpers ─────────────────────────────────────────────────────────────

def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_OUT_CHANNELS)
        wf.setsampwidth(_OUT_SAMPLE_WIDTH)
        wf.setframerate(_OUT_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _wav_duration_ms(wav: bytes) -> int:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)


def _extract_pcm(response) -> Optional[bytes]:
    """Extract raw PCM bytes from a Gemini Live response (handles SDK variations)."""
    d = getattr(response, "data", None)
    if d and isinstance(d, bytes):
        return d
    sc = getattr(response, "server_content", None)
    if sc:
        mt = getattr(sc, "model_turn", None)
        if mt:
            for part in getattr(mt, "parts", []) or []:
                raw = getattr(getattr(part, "inline_data", None), "data", None)
                if raw:
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
    return None


def _extract_text(response) -> Optional[str]:
    """
    Extract spoken transcript text (not thought/reasoning) from Gemini Live response.
    Gemini 2.5 Flash generates text alongside audio; filter out 'thought' parts.
    """
    sc = getattr(response, "server_content", None)
    if not sc:
        return None
    mt = getattr(sc, "model_turn", None)
    if not mt:
        return None
    parts = [
        getattr(p, "text", "")
        for p in getattr(mt, "parts", []) or []
        if not getattr(p, "thought", False) and getattr(p, "text", "")
    ]
    return " ".join(parts) if parts else None


def _extract_output_transcription(response) -> Optional[str]:
    """Model's spoken words as text (output_audio_transcription). Drives captions."""
    sc = getattr(response, "server_content", None)
    if not sc:
        return None
    ot = getattr(sc, "output_transcription", None)
    txt = getattr(ot, "text", None) if ot else None
    return txt or None


def _extract_input_transcription(response) -> Optional[str]:
    """User's spoken words as text (input_audio_transcription). Drives draft intent in mic mode."""
    sc = getattr(response, "server_content", None)
    if not sc:
        return None
    it = getattr(sc, "input_transcription", None)
    txt = getattr(it, "text", None) if it else None
    return txt or None


def _is_turn_complete(response) -> bool:
    sc = getattr(response, "server_content", None)
    return bool(sc and getattr(sc, "turn_complete", False))


def _is_interrupted(response) -> bool:
    sc = getattr(response, "server_content", None)
    return bool(sc and getattr(sc, "interrupted", False))


# ── Context builder ───────────────────────────────────────────────────────────

def _build_live_system_prompt(session_obj) -> str:
    """Compact system prompt for Gemini Live (~200 tokens)."""
    rr = session_obj.risk_report or {}
    overall        = rr.get("overall_risk", "Unknown")
    contract_type  = rr.get("contract_type", "contract")
    recommendation = rr.get("final_recommendation", "Review carefully")

    top_risks = [
        f"• {r['title']}: {r.get('simple_explanation', '')}"
        for r in rr.get("risks", [])
        if r.get("severity") in ("High", "Critical")
    ][:3]

    active_id   = getattr(session_obj, "active_clause_id", None)
    active_line = f"\nCurrent focus: clause {active_id}" if active_id else ""

    return f"""\
You are ProtectMe AI, a contract-risk voice agent in a live call.
Contract: {contract_type} | Risk: {overall} | Advice: {recommendation}

Top risks:
{chr(10).join(top_risks) if top_risks else "• None identified."}
{active_line}

Voice rules:
- MAX 2 short sentences per reply. Key finding first.
- Warm, direct tone. Not a lawyer. Not legal advice.
- If asked to draft/write a message, say: "I can draft that for you." (the system will generate the draft automatically)"""


# ── Draft generation (hybrid) ─────────────────────────────────────────────────

async def _maybe_generate_draft(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    model_text: str,
    session_id: str,
) -> None:
    """
    If the model's spoken text suggests drafting a message, generate one
    using the Gemini conversation model and emit a draft_ready event.

    This hybrid ensures the actual draft appears in the UI even in audio-only mode.
    """
    matched = bool(_DRAFT_RE.search(model_text))
    logger.info(
        "Draft check — session=%s matched=%s user_said=%r",
        session_id, matched, model_text[:80],
    )
    if not matched:
        return

    session_obj = session_repository.get(session_id)
    if not session_obj or not session_obj.risk_report:
        return

    risks     = session_obj.risk_report.get("risks", [])
    active_id = getattr(session_obj, "active_clause_id", None)

    clause = (
        next((r for r in risks if r.get("id") == active_id), None)
        if active_id
        else (risks[0] if risks else None)
    )
    if not clause:
        logger.warning("Draft triggered but no clause found — session %s", session_id)
        return

    async with send_lock:
        await websocket.send_json({
            "type": "status", "state": "tool_running", "label": "Drafting message…"
        })

    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        model  = settings.gemini_conversation_model or "gemini-2.0-flash"

        prompt = (
            f"Write a professional, polite email to a landlord/counterparty regarding "
            f"this contract clause:\n\n"
            f"Clause title: {clause.get('title', '')}\n"
            f"What it means: {clause.get('simple_explanation', clause.get('clause_text', ''))}\n\n"
            f"Write only the email. Use [Your Name] as placeholder. "
            f"Be concise, clear, and respectful. "
            f"Ask them to clarify or revise this clause before signing."
        )

        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
        )
        draft = (response.text or "").strip()

        if draft:
            async with send_lock:
                await websocket.send_json({
                    "type":       "draft_ready",
                    "draft":      draft,
                    "clause_ids": [clause.get("id", "")],
                })
                await websocket.send_json({
                    "type": "debug",
                    "log":  f"[Live] draft_ready — {len(draft)} chars for clause {clause.get('id')}",
                })
        else:
            logger.warning("Draft generation returned empty text for session %s", session_id)

    except Exception as exc:
        logger.error("Draft generation failed (session %s): %s", session_id, exc)
    finally:
        async with send_lock:
            await websocket.send_json({
                "type": "status", "state": "idle", "label": "Listening…"
            })


# ── Concurrent streaming tasks ─────────────────────────────────────────────────

async def _send_debug(websocket: WebSocket, send_lock: asyncio.Lock, log: str) -> None:
    """Send a [Live] debug event to the browser (drives the debug terminal)."""
    try:
        async with send_lock:
            await websocket.send_json({"type": "debug", "log": log})
    except Exception:
        pass


async def _ws_to_live(
    websocket: WebSocket,
    live_session,
    send_lock: asyncio.Lock,
    stop: asyncio.Event,
    types,
    turn_state: dict,
    stats: dict,
) -> None:
    """
    Task 1: Read audio/text from the browser WebSocket, forward to Gemini Live.
    Records the user's text (text_input) into turn_state for draft-intent detection.
    Exits on WebSocketDisconnect, stop event, or unrecoverable error.
    """
    try:
        while not stop.is_set():
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            msg_type = data.get("type", "")

            if msg_type == "audio_input":
                pcm = base64.b64decode(data.get("audio", ""))
                if pcm:
                    stats["in_chunks"] += 1
                    n = stats["in_chunks"]
                    if n == 1 or n % 25 == 0:
                        await _send_debug(
                            websocket, send_lock,
                            f"[Live] received audio_input chunk #{n}",
                        )
                    await live_session.send_realtime_input(
                        audio=types.Blob(data=pcm, mime_type=_IN_MIME)
                    )

            elif msg_type in ("text_input", "transcript"):
                text = data.get("text", "").strip()
                if text:
                    turn_state["user_text"] = text  
                    await live_session.send_client_content(
                        turns=[types.Content(
                            parts=[types.Part(text=text)],
                            role="user",
                        )],
                        turn_complete=True,
                    )
                    async with send_lock:
                        await websocket.send_json({
                            "type": "status", "state": "thinking", "label": "Thinking…"
                        })

            elif msg_type == "end_audio_turn":
                try:
                    await live_session.send_realtime_input(audio_stream_end=True)
                    await _send_debug(websocket, send_lock, "[Live] audio_stream_end sent (mic released)")
                except Exception as exc:
                    logger.error("end_audio_turn failed: %s", exc)

            elif msg_type == "stop":
                break

    except WebSocketDisconnect:
        logger.info("Live WS disconnected (ws_to_live)")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("ws_to_live error: %s", exc)
    finally:
        stop.set()


async def _live_to_ws(
    websocket: WebSocket,
    live_session,
    send_lock: asyncio.Lock,
    stop: asyncio.Event,
    session_id: str,
    turn_state: dict,
    stats: dict,
) -> None:
    """
    Task 2: Stream Gemini Live audio + text to the browser.

    Lifecycle: the SDK's session.receive() generator yields one model turn then
    ends (it breaks on turn_complete — see google/genai/live.py). To keep the
    call alive across many turns we call receive() again in an OUTER loop. The
    underlying WebSocket session (the connect() context) stays open the whole
    time, so the browser call does NOT end after a single reply.

    The outer loop exits only when: stop is set (user ended / disconnect), a
    receive() yields nothing (server closed the socket), or an error occurs.

    Buffers PCM into 300ms WAV chunks. Uses output transcription for live captions.
    Detects draft intent from the USER's words (text_input + input transcription).
    """
    turn_id: int = 0

    try:
        while not stop.is_set():
            seq: int              = 0
            pcm_buf: bytes        = b""
            user_transcript: str  = ""  
            t_first_audio: Optional[float] = None
            t_turn_start: float   = 0.0
            in_turn: bool         = False
            got_any: bool         = False   

            async for response in live_session.receive():
                got_any = True
                if stop.is_set():
                    break

                pcm = _extract_pcm(response)
                if pcm:
                    if not in_turn:
                        in_turn       = True
                        t_turn_start  = time.monotonic()
                        t_first_audio = None
                        seq           = 0
                        pcm_buf       = b""
                        turn_id      += 1
                        async with send_lock:
                            await websocket.send_json({
                                "type": "status", "state": "speaking", "label": "Speaking…"
                            })

                    if t_first_audio is None:
                        t_first_audio = time.monotonic() - t_turn_start
                        logger.info(
                            "Live first audio — turn=%d t_first=%.2fs session=%s",
                            turn_id, t_first_audio, session_id,
                        )

                    pcm_buf += pcm

                    if len(pcm_buf) >= _PCM_CHUNK_BYTES:
                        wav = _pcm_to_wav(pcm_buf)
                        dur = _wav_duration_ms(wav)
                        stats["out_chunks"] += 1
                        async with send_lock:
                            await websocket.send_json({
                                "type":        "audio_chunk",
                                "turn_id":     turn_id,
                                "seq":         seq,
                                "text":        "",
                                "audio":       base64.b64encode(wav).decode(),
                                "mime":        "audio/wav",
                                "duration_ms": dur,
                            })
                            await websocket.send_json({
                                "type": "debug",
                                "log": (
                                    f"[Live] sent audio chunk seq={seq} turn={turn_id} dur={dur}ms"
                                    + (f" (first_audio={t_first_audio:.2f}s)" if seq == 0 else "")
                                ),
                            })
                        seq    += 1
                        pcm_buf = b""

                cap = _extract_output_transcription(response) or _extract_text(response)
                if cap:
                    async with send_lock:
                        await websocket.send_json({"type": "sentence", "text": cap})

                in_tx = _extract_input_transcription(response)
                if in_tx:
                    user_transcript += " " + in_tx

                if _is_turn_complete(response) or _is_interrupted(response):
                    if pcm_buf:
                        wav = _pcm_to_wav(pcm_buf)
                        dur = _wav_duration_ms(wav)
                        stats["out_chunks"] += 1
                        async with send_lock:
                            await websocket.send_json({
                                "type":        "audio_chunk",
                                "turn_id":     turn_id,
                                "seq":         seq,
                                "text":        "",
                                "audio":       base64.b64encode(wav).decode(),
                                "mime":        "audio/wav",
                                "duration_ms": dur,
                            })
                        pcm_buf = b""

                    t_done = time.monotonic() - t_turn_start if in_turn else 0.0
                    async with send_lock:
                        await websocket.send_json({"type": "audio_done", "turn_id": turn_id})
                        await websocket.send_json({
                            "type": "debug",
                            "log": (
                                f"[Live] turn={turn_id} done | "
                                f"t_first={t_first_audio:.2f}s | t_total={t_done:.2f}s | "
                                f"{'interrupted' if _is_interrupted(response) else 'complete'}"
                            ) if t_first_audio is not None else (
                                f"[Live] turn={turn_id} done (no audio this turn)"
                            ),
                        })
                        await websocket.send_json({
                            "type": "status", "state": "idle", "label": "Listening…"
                        })

                    user_said = (turn_state.get("user_text", "") + " " + user_transcript).strip()
                    turn_state["user_text"] = "" 
                    user_transcript = ""
                    if user_said:
                        await _maybe_generate_draft(websocket, send_lock, user_said, session_id)

                    in_turn = False
                    break   

            if not got_any:
                logger.info("Live receive() ended with no data — session %s closed", session_id)
                break

    except WebSocketDisconnect:
        logger.info("Live WS disconnected (live_to_ws)")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("live_to_ws error (session %s): %s", session_id, exc)
        await _send_debug(websocket, send_lock, f"[Live] error={type(exc).__name__}: {exc}")
    finally:
        stop.set()


# ── Service ───────────────────────────────────────────────────────────────────

class LiveVoiceService:

    async def handle_live_session(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> None:
        if not settings.is_gemini_configured:
            raise GeminiNotConfiguredError()
        if not session_repository.exists(session_id):
            raise SessionNotFoundError(session_id)

        session_obj = session_repository.get(session_id)

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            await websocket.send_json({
                "type": "error",
                "message": "Gemini SDK not available. Use /ws/voice/ instead.",
            })
            await websocket.close(code=1011)
            return

        live_model    = settings.gemini_live_model or _LIVE_MODEL_DEFAULT
        system_prompt = _build_live_system_prompt(session_obj)

        try:
            live_config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=types.Content(
                    parts=[types.Part(text=system_prompt)],
                    role="user",
                ),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=_LIVE_VOICE,
                        )
                    )
                ),
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
            )
        except Exception as exc:
            logger.error("Failed to build Live config: %s", exc)
            await websocket.send_json({
                "type": "error",
                "message": "Live config failed. Use /ws/voice/ instead.",
            })
            await websocket.close(code=1011)
            return

        client     = genai.Client(api_key=settings.gemini_api_key)
        send_lock  = asyncio.Lock()
        stop       = asyncio.Event()
        turn_state: dict = {"user_text": ""}  
        stats: dict      = {"in_chunks": 0, "out_chunks": 0}

        logger.info("Opening Live session — model=%s session=%s", live_model, session_id)
        await _send_debug(websocket, send_lock, "[Live] session loaded")

        try:
            async with client.aio.live.connect(model=live_model, config=live_config) as live_session:
                async with send_lock:
                    await websocket.send_json({
                        "type": "status", "state": "idle", "label": "Live — speak now"
                    })
                    await websocket.send_json({
                        "type": "debug",
                        "log":  f"[Live] Gemini Live session opened — {live_model} | audio-in/audio-out",
                    })
                    await websocket.send_json({
                        "type": "sentence",
                        "text": "Live voice active. Speak naturally — I'm listening.",
                    })

                task_send = asyncio.create_task(
                    _ws_to_live(websocket, live_session, send_lock, stop, types, turn_state, stats),
                    name="ws_to_live",
                )
                task_recv = asyncio.create_task(
                    _live_to_ws(websocket, live_session, send_lock, stop, session_id, turn_state, stats),
                    name="live_to_ws",
                )

                done, pending = await asyncio.wait(
                    {task_send, task_recv},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for t in done:
                    exc = t.exception()
                    if exc:
                        logger.error("Live task %s raised: %s", t.get_name(), exc)

                logger.info(
                    "Live session closed — session=%s in_chunks=%d out_chunks=%d",
                    session_id, stats["in_chunks"], stats["out_chunks"],
                )
                await _send_debug(
                    websocket, send_lock,
                    f"[Live] Gemini Live session closed "
                    f"(audio_input received={stats['in_chunks']}, audio chunks sent={stats['out_chunks']})",
                )

        except WebSocketDisconnect:
            logger.info("WS disconnected before Live session — %s", session_id)
        except Exception as exc:
            logger.error("Gemini Live session failed — %s: %s", session_id, exc)
            try:
                async with send_lock:
                    await websocket.send_json({
                        "type": "error",
                        "message": (
                            f"Gemini Live unavailable ({type(exc).__name__}). "
                            "Reconnect and switch to standard voice mode."
                        ),
                    })
                    await websocket.close(code=1011)
            except Exception:
                pass


live_voice_service = LiveVoiceService()
