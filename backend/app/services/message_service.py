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


def _has_arabic(text: str) -> bool:
    """True if the text contains any Arabic character (U+0600–U+06FF)."""
    return any("؀" <= ch <= "ۿ" for ch in (text or ""))


# English email/letter scaffolding that must NEVER appear in an Arabic draft.
_ENGLISH_TEMPLATE_MARKERS = (
    "subject:", "dear ", "best regards", "kind regards", "warm regards",
    "i hope this email finds you well", "to whom it may concern",
    "sincerely,", "clarification request", "yours faithfully",
)


def _is_acceptable_arabic(text: str) -> bool:
    """An Arabic draft must (1) avoid English template scaffolding (Subject:, Dear,
    Best regards, …) and (2) be predominantly Arabic — Arabic letters must at least
    match the Latin letters, so an English-heavy draft with a few Arabic words is
    rejected and routed to the deterministic Arabic fallback."""
    if not text:
        return False
    low = text.lower()
    if any(marker in low for marker in _ENGLISH_TEMPLATE_MARKERS):
        return False
    arabic = sum(1 for ch in text if "؀" <= ch <= "ۿ")
    latin = sum(1 for ch in text if "a" <= ch <= "z" or "A" <= ch <= "Z")
    return arabic > 0 and arabic >= latin


# Deterministic Arabic message templates — used only as a last-resort fallback if
# the model fails to produce Arabic after a retry. Guarantees the dashboard never
# shows an English draft in Arabic mode.
_AR_SUBJECT = {
    "clarification": "طلب توضيح بخصوص بنود العقد",
    "negotiation": "طلب التفاوض بشأن بعض بنود العقد",
    "rejection": "تحفّظات على بعض بنود العقد",
    "amendment_request": "طلب تعديل بعض بنود العقد",
}
_AR_OPENING = {
    "clarification": "أكتب إليكم لطلب توضيح بخصوص بعض البنود في العقد:",
    "negotiation": "أكتب إليكم لمناقشة بعض البنود في العقد والتفاوض بشأنها:",
    "rejection": "أكتب إليكم لإبداء بعض التحفّظات على بنود في العقد:",
    "amendment_request": "أكتب إليكم لطلب تعديل بعض البنود في العقد:",
}


def _arabic_fallback_draft(selected, message_type, tone, format, extra_instruction):
    """Build a deterministic Arabic draft from the selected risks (no model call)."""
    subject = _AR_SUBJECT.get(message_type, _AR_SUBJECT["clarification"])
    opening = _AR_OPENING.get(message_type, _AR_OPENING["clarification"])
    bullets = [
        f"- {r.get('title', '').strip()}: {r.get('simple_explanation', '').strip()}".rstrip(": ")
        for r in selected
    ]
    note = f"ملاحظة إضافية: {extra_instruction.strip()}" if extra_instruction else ""
    closing_request = (
        "أتوقّع توضيح هذه النقاط أو تعديلها قبل المتابعة."
        if str(tone).lower() == "firm"
        else "أرجو منكم التكرّم بتوضيح هذه النقاط أو إعادة النظر فيها قبل المتابعة."
    )

    if str(format).lower() == "whatsapp":
        # Short, conversational — no subject line or formal headers.
        titles = "، ".join(r.get("title", "").strip() for r in selected if r.get("title"))
        parts = [f"مرحباً، {opening}"]
        if titles:
            parts.append(titles + ".")
        if note:
            parts.append(note + ".")
        parts.append("هل يمكن توضيح ذلك أو إعادة النظر فيه؟ شكراً لك.")
        return " ".join(parts)

    # Email — Arabic subject, greeting, body, closing.
    lines = [
        f"الموضوع: {subject}",
        "",
        "مرحباً [اسم المستلم]،",
        "",
        opening,
        "",
        *bullets,
    ]
    if note:
        lines += ["", note]
    lines += ["", closing_request, "", "مع خالص التحية،", "[اسمك]"]
    return "\n".join(lines)


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

        # Language ('ar' or 'en', from the X-Language header). For Arabic the prompt
        # builder adds a strong Arabic-only directive (subject/greeting/body/closing
        # all in Arabic). The chosen format (email/WhatsApp) and any user-supplied
        # custom details (request.extra_instruction) are still honored.
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

        # extra_instruction carries only the user's custom details — the Arabic
        # language enforcement lives in the prompt (driven by `language`).
        extra_instruction = request.extra_instruction or None

        logger.info(
            "[MessageService] Generating %s/%s/%s (lang=%s) for %d clause(s).",
            request.message_type.value,
            request.tone.value,
            request.format.value,
            lang,
            len(selected),
        )

        async def _generate(extra):
            return await tool.execute(
                clause_texts=clause_texts,
                risk_titles=risk_titles,
                message_type=request.message_type.value,
                tone=request.tone.value,
                format=request.format.value,
                gemini_client=client,
                extra_instruction=extra,
                language=lang,
            )

        try:
            draft = await _generate(extra_instruction)
            # Arabic guarantee: the draft must be Arabic with no English email
            # scaffolding ("Subject:", "Dear", "Best regards"). If not, retry once
            # with a blunt directive; if it still fails, fall back to a deterministic
            # Arabic draft so the dashboard never shows English in Arabic mode.
            if lang == "ar" and not _is_acceptable_arabic(draft):
                logger.warning(
                    "[MessageService] Arabic requested but draft looked English; retrying once."
                )
                retry_extra = " ".join(
                    p for p in (
                        extra_instruction,
                        "CRITICAL: Your previous attempt was written in English. Rewrite the "
                        "ENTIRE message in Arabic (العربية) only — the subject line, greeting, "
                        'body, and closing. Output no English at all; use "الموضوع:" for the '
                        'subject, never "Subject:".',
                    ) if p
                )
                draft = await _generate(retry_extra)
                if not _is_acceptable_arabic(draft):
                    logger.warning(
                        "[MessageService] Retry still not Arabic; using deterministic Arabic fallback."
                    )
                    draft = _arabic_fallback_draft(
                        selected,
                        request.message_type.value,
                        request.tone.value,
                        request.format.value,
                        extra_instruction,
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
