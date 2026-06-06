"""
MessageService — generates professional draft messages from selected contract risks.

Wires the backend HTTP layer to the agent's GenerateMessageTool.
sys.path injection mirrors contract_service.py so the agent package is importable.
"""
import logging
import sys
from pathlib import Path

# message_service.py → services/ → app/ → backend/ → project root → agent/
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from app.core.config import settings
from app.core.exceptions import (
    ClauseNotFoundError,
    GeminiNotConfiguredError,
    MessageGenerationError,
    NoRiskReportError,
)
from app.schemas.message_schema import GenerateMessageRequest, GenerateMessageResponse
from app.schemas.session_schema import GeneratedMessage
from app.services.session_service import session_service

logger = logging.getLogger(__name__)


def _build_gemini_client():
    """Create a GeminiClient using current settings."""
    from protectme_agent.gemini_client import GeminiClient

    return GeminiClient(
        api_key=settings.gemini_api_key,
        analysis_model=settings.gemini_analysis_model,
        conversation_model=settings.gemini_conversation_model,
        live_model=settings.gemini_live_model,
    )


class MessageService:
    """Generates professional messages from selected contract risks."""

    async def generate_message(
        self, request: GenerateMessageRequest, language: str = "en"
    ) -> GenerateMessageResponse:
        if not settings.is_gemini_configured:
            raise GeminiNotConfiguredError()

        # Language ('ar' or 'en', from the X-Language header). For Arabic we prepend
        # a directive to the model's extra instruction so the whole draft is written
        # in Arabic — the chosen format (email/WhatsApp) and any user-supplied custom
        # details (request.extra_instruction) are still honored.
        lang = "ar" if str(language or "").strip().lower().startswith("ar") else "en"

        session = session_service.get_session(request.session_id)

        if not session.risk_report:
            raise NoRiskReportError()

        risks = session.risk_report.get("risks", [])
        risk_map = {r["id"]: r for r in risks}

        missing = [cid for cid in request.clause_ids if cid not in risk_map]
        if missing:
            raise ClauseNotFoundError(missing)

        selected = [risk_map[cid] for cid in request.clause_ids]
        clause_texts = [r.get("clause_text", "") for r in selected]
        risk_titles = [
            f"{r['title']}: {r.get('simple_explanation', '')}" for r in selected
        ]

        from protectme_agent.tools.generate_message_tool import GenerateMessageTool

        tool = GenerateMessageTool()
        client = _build_gemini_client()

        # For Arabic, the language directive leads so it is unambiguous, then any
        # user-supplied custom details follow. English keeps the request as-is.
        extra_parts = []
        if lang == "ar":
            extra_parts.append(
                "Write the entire message in Arabic (العربية), using clear, natural, "
                "professional Arabic. Keep any names, numbers, and dates accurate."
            )
        if request.extra_instruction:
            extra_parts.append(request.extra_instruction)
        extra_instruction = " ".join(extra_parts) or None

        logger.info(
            "[MessageService] Generating %s/%s/%s (lang=%s) for %d clause(s).",
            request.message_type.value,
            request.tone.value,
            request.format.value,
            lang,
            len(selected),
        )

        try:
            draft = await tool.execute(
                clause_texts=clause_texts,
                risk_titles=risk_titles,
                message_type=request.message_type.value,
                tone=request.tone.value,
                format=request.format.value,
                gemini_client=client,
                extra_instruction=extra_instruction,
            )
        except Exception as exc:
            logger.error("[MessageService] Generation failed: %s", exc)
            raise MessageGenerationError(str(exc)) from exc

        generated = GeneratedMessage(
            clause_ids=request.clause_ids,
            message_type=request.message_type.value,
            tone=request.tone.value,
            format=request.format.value,
            draft=draft,
        )
        session_service.add_generated_message(request.session_id, generated)

        logger.info("[MessageService] Draft generated (%d chars).", len(draft))

        return GenerateMessageResponse(
            draft=draft,
            session_id=request.session_id,
            clause_ids=request.clause_ids,
            message_type=request.message_type.value,
            tone=request.tone.value,
            format=request.format.value,
        )


message_service = MessageService()
