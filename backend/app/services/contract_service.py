"""
ContractService — orchestrates the full contract analysis workflow.

Makes the agent package importable from the backend by adding the agent/
directory to sys.path before any agent imports happen.
"""
import logging
import sys
from pathlib import Path

# ── Make the agent package importable ────────────────────────────────────────
# contract_service.py → services/ → app/ → backend/ → protectme-ai-agent/ → agent/
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from app.core.config import settings
from app.core.exceptions import (
    ContractAnalysisError,
    GeminiNotConfiguredError,
    InvalidContractError,
)
from app.repositories.session_repository import session_repository
from app.schemas.session_schema import Session
from app.utils.file_utils import extract_text_from_pdf
from app.utils.text_utils import clean_contract_text, truncate_contract_text

logger = logging.getLogger(__name__)


_orchestrator = None


def _get_orchestrator():
    """Return the singleton Orchestrator, creating it on first call."""
    global _orchestrator
    if _orchestrator is None:
        from protectme_agent.gemini_client import GeminiClient
        from protectme_agent.orchestrator import Orchestrator

        client = GeminiClient(
            api_key=settings.gemini_api_key,
            analysis_model=settings.gemini_analysis_model,
            conversation_model=settings.gemini_conversation_model,
            live_model=settings.gemini_live_model,
        )
        _orchestrator = Orchestrator(gemini_client=client)
        logger.info("[Agent] Orchestrator initialized (singleton).")
    return _orchestrator


class ContractService:
    """Orchestrates contract analysis: text/PDF in → session with risk report out."""

    async def analyze_from_text(self, text: str, language: str = "en") -> Session:
        """Analyze raw contract text and persist a new session.
        language='ar' makes the user-facing risk fields Arabic; it is also stored
        on the session so the voice agent can default to that language."""
        if not settings.is_gemini_configured:
            raise GeminiNotConfiguredError()
        if not text or not text.strip():
            raise InvalidContractError("Contract text cannot be empty.")

        lang = "ar" if str(language or "").lower().startswith("ar") else "en"
        logger.info("[Agent] Upload received — analyzing contract text (lang=%s).", lang)

        clean = clean_contract_text(text)
        truncated = truncate_contract_text(clean)

        logger.info("[Agent] Extracting contract text — %d characters.", len(truncated))

        try:
            orchestrator = _get_orchestrator()
            logger.info("[Agent] Gemini Pro analysis started.")
            risk_report_dict = await orchestrator.analyze_contract(truncated, language=lang)
        except Exception as exc:
            logger.error("[Agent] Analysis failed: %s", exc)
            raise ContractAnalysisError(str(exc)) from exc

        risk_count = len(risk_report_dict.get("risks", []))
        logger.info("[Agent] Structured JSON generated — %d risks detected.", risk_count)

        session = session_repository.create()
        session_repository.update(
            session.session_id,
            contract_text=truncated,
            risk_report=risk_report_dict,
            language=lang,
            debug_logs=[
                "[Agent] Upload received",
                "[Agent] Extracting contract text",
                "[Agent] Gemini Pro analysis started",
                "[Agent] Structured JSON generated",
                f"[Agent] {risk_count} risks detected",
            ],
        )
        # Return the updated session
        return session_repository.get(session.session_id)

    async def analyze_from_pdf(self, file_bytes: bytes, filename: str, language: str = "en") -> Session:
        """Extract text from a PDF and run the standard analysis pipeline."""
        if not settings.is_gemini_configured:
            raise GeminiNotConfiguredError()

        logger.info("[Agent] PDF upload received — extracting text from '%s'.", filename)
        try:
            text = extract_text_from_pdf(file_bytes)
        except ValueError as exc:
            raise InvalidContractError(str(exc)) from exc
        except RuntimeError as exc:
            raise ContractAnalysisError(str(exc)) from exc

        return await self.analyze_from_text(text, language=language)


contract_service = ContractService()
