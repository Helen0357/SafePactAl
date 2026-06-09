import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import register_exception_handlers
from app.api.routes import (
    contract_routes,
    live_routes,
    message_routes,
    report_routes,
    session_routes,
    voice_routes,
)
from app.repositories.session_repository import session_repository
from app.services.session_service import session_service

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  %s  v%s  starting up", settings.app_name, settings.app_version)
    logger.info("=" * 60)

    for warning in settings.configuration_warnings:
        logger.warning(warning)

    if settings.is_gemini_configured:
        logger.info(
            "Gemini configured — analysis model: %s | conversation model: %s",
            settings.gemini_analysis_model or "(not set)",
            settings.gemini_conversation_model or "(not set)",
        )
    else:
        logger.warning(
            "Gemini API key is NOT set. "
            "Contract analysis and message generation will return 503 until configured."
        )

    # ── Google Cloud credentials ───────────────────────────────────────────────
    if settings.google_application_credentials:
        creds_path = Path(settings.google_application_credentials)
        if not creds_path.is_absolute():
            backend_root = Path(__file__).parent.parent   # backend/app -> backend/
            creds_path = (backend_root / creds_path).resolve()
        if creds_path.exists():
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(creds_path))
            logger.info("Google Cloud TTS credentials configured.")
        else:
            logger.warning(
                "GOOGLE_APPLICATION_CREDENTIALS path not found — GCP TTS disabled."
            )

    if settings.is_gemini_configured:
        logger.info("Pre-warming Gemini client (first init may take up to 100s on cold start)...")
        try:
            from app.services.contract_service import _get_orchestrator
            _get_orchestrator()
            logger.info("Gemini client warm-up complete.")
        except Exception as exc:
            logger.warning("Gemini client warm-up failed: %s", exc)

    asyncio.create_task(_warmup_tts())

    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    logger.info(
        "Session cleanup task started (TTL: %d min, interval: 5 min).",
        settings.session_ttl_minutes,
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("%s shut down cleanly.", settings.app_name)


async def _warmup_tts() -> None:
    """
    Prime the TTS connection pool at startup so the first real synthesis is fast.
    Runs in background — app startup is not blocked if TTS is unavailable.
    """
    try:
        from protectme_agent.streaming.tts_service import synthesize_speech_fast
        result = await synthesize_speech_fast(
            "Ready.",
            google_cloud_api_key=settings.google_cloud_tts_api_key,
            gemini_api_key=settings.gemini_api_key,
            voice_name=settings.google_cloud_tts_voice,  
        )
        if result:
            logger.info("TTS warm-up OK — %d bytes synthesized.", len(result))
        else:
            logger.warning(
                "TTS warm-up returned None. "
                "Check GOOGLE_CLOUD_TTS_API_KEY or GEMINI_API_KEY."
            )
    except Exception as exc:
        logger.warning("TTS warm-up failed (non-fatal): %s", exc)


async def _session_cleanup_loop() -> None:
    """Periodically evict sessions that have been idle beyond TTL."""
    while True:
        await asyncio.sleep(300)  
        try:
            session_service.cleanup_expired_sessions()
        except Exception:
            logger.exception("Error during session cleanup.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "ProtectMe AI — Contract risk dashboard and streaming voice agent. "
        "Understand before you sign. Ask before you agree."
    ),
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(contract_routes.router, prefix="/api/contracts", tags=["Contracts"])
app.include_router(message_routes.router, prefix="/api/actions", tags=["Actions"])
app.include_router(session_routes.router, prefix="/api/session", tags=["Session"])
app.include_router(report_routes.router, prefix="/api/reports", tags=["Reports"])
app.include_router(voice_routes.router, tags=["Voice"])
app.include_router(live_routes.router,  tags=["Voice-Live"])


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"], summary="Health check")
async def health_check():
    """Returns service status, version, Gemini configuration state, and active session count."""
    missing = settings.missing_required_vars
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "gemini_configured": settings.is_gemini_configured,
        "missing_env_vars": missing if missing else None,
        "active_sessions": session_repository.count,
    }
