import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.exceptions import GeminiNotConfiguredError, SessionNotFoundError
from app.services.voice_service import voice_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/voice/{session_id}")
async def voice_websocket(
    websocket: WebSocket,
    session_id: str,
    language: str = Query("en", description="UI language: 'en' or 'ar'"),
):
    """
    Real-time bidirectional voice agent session.

    Client → Server:
      {type: "transcript", text: "..."}   — from browser SpeechRecognition
      {type: "text_input",  text: "..."}  — from text fallback input

    Server → Client:
      {type: "sentence",    text: "..."}
      {type: "audio_chunk", turn_id: 1, seq: 0, text: "...", audio: "<base64-wav>", mime: "audio/wav"}
      {type: "audio_done"}
      {type: "tts_error",   seq: 0, text: "...", message: "..."}
      {type: "status",      state: "...", label: "..."}
      {type: "tool_result", tool: "...", result: {...}}
      {type: "draft_ready", draft: "...", clause_ids: [...]}
      {type: "debug",       log: "..."}
      {type: "error",       message: "..."}
    """
    await websocket.accept()
    lang = "ar" if str(language or "").strip().lower().startswith("ar") else "en"
    logger.info("WS connected — session: %s (lang=%s)", session_id, lang)
    try:
        await voice_service.handle_voice_session(session_id, websocket, language=lang)
    except SessionNotFoundError as exc:
        await websocket.send_json({"type": "error", "message": exc.message})
        await websocket.close(code=1008)
    except GeminiNotConfiguredError as exc:
        await websocket.send_json({"type": "error", "message": exc.message})
        await websocket.close(code=1011)
    except WebSocketDisconnect:
        logger.info("WS disconnected — session: %s", session_id)
    except Exception:
        logger.exception("WS unhandled error — session: %s", session_id)
        try:
            await websocket.send_json(
                {"type": "error", "message": "An unexpected error occurred."}
            )
            await websocket.close(code=1011)
        except Exception:
            pass
