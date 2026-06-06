"""
Phase 8I follow-up — language-aware drafts + Arabic PDF voice command.

  • REST /api/actions/generate-message honors X-Language: ar → Arabic draft directive
    (chosen format + user custom details still respected)
  • REST default / X-Language: en → no Arabic directive (English unchanged)
  • Arabic download/report/file phrases trigger the download_pdf event (no Gemini)
  • "هل يمكنك ان تقوم بتنزيل الملف" triggers download_pdf, in Arabic
  • English "download the PDF" still triggers download_pdf

Gemini mocked — fast, no quota.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# tests/ → backend/ → protectme-ai-agent/ → agent/
_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.session_repository import session_repository
from app.schemas.session_schema import Session

client = TestClient(app)

REPORT = {
    "contract_type": "Rental Agreement",
    "overall_risk": "High",
    "final_recommendation": "Do Not Sign Yet",
    "summary": "Risky.",
    "confidence": 0.9,
    "risks": [
        {"id": "risk_001", "title": "Deposit Forfeiture", "severity": "High",
         "category": "Deposit", "clause_text": "Forfeit deposit.",
         "simple_explanation": "You lose your deposit.", "why_it_matters": "Costly.",
         "question_to_ask": "Pro-rate?", "suggested_action": "Negotiate"},
    ],
    "missing_information": [], "recommended_questions": [],
}


def _make_session() -> str:
    s = Session(risk_report=REPORT, contract_text="x")
    session_repository.create(s)
    return s.session_id


def _mock_gemini(draft_text: str = "مسودة عربية."):
    mock = MagicMock()
    mock.conversation_model = "gemini-3.5-flash"
    mock.generate = AsyncMock(return_value=draft_text)
    return mock


# ── REST generate-message X-Language (Issue 1) ─────────────────────────────────

class TestGenerateMessageLanguage:
    """The X-Language header drives the language of the generated draft."""

    def _post(self, sid, mock_client, headers=None, **body_overrides):
        body = {
            "session_id": sid,
            "clause_ids": ["risk_001"],
            "message_type": "clarification",
            "tone": "polite",
            "format": "email",
        }
        body.update(body_overrides)
        with patch("app.services.message_service._build_gemini_client",
                   return_value=mock_client):
            return client.post("/api/actions/generate-message",
                               json=body, headers=headers or {})

    def test_arabic_header_adds_arabic_directive(self):
        mock_client = _mock_gemini()
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "ar"})
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" in prompt          # Arabic directive present
        assert "email" in prompt.lower()    # chosen format still respected

    def test_arabic_header_preserves_custom_details(self):
        mock_client = _mock_gemini()
        resp = self._post(
            _make_session(), mock_client, headers={"X-Language": "ar"},
            format="whatsapp",
            extra_instruction="Mention my move-in date is July 1.",
        )
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" in prompt           # Arabic directive present
        assert "July 1" in prompt            # user's custom detail preserved
        assert "whatsapp" in prompt.lower()  # chosen format still respected

    def test_english_default_has_no_arabic_directive(self):
        mock_client = _mock_gemini("English draft.")
        resp = self._post(_make_session(), mock_client)  # no X-Language header
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" not in prompt       # English unchanged

    def test_english_header_has_no_arabic_directive(self):
        mock_client = _mock_gemini("English draft.")
        resp = self._post(_make_session(), mock_client, headers={"X-Language": "en"})
        assert resp.status_code == 200
        prompt = mock_client.generate.call_args.kwargs["prompt"]
        assert "العربية" not in prompt


# ── Arabic PDF voice command → download_pdf event (Issue 2) ────────────────────

class TestArabicPdfVoiceCommand:
    def test_wants_pdf_arabic_phrases(self):
        from protectme_agent.fast_path import wants_pdf
        for phrase in [
            "تنزيل الملف", "تحميل الملف", "نزل الملف", "حمل الملف",
            "حمّل الملف", "نزّل الملف", "تنزيل التقرير", "تحميل التقرير",
            "حمل التقرير", "نزل التقرير", "صدّر التقرير", "اعمل ملف",
            "اعمل PDF", "ملف PDF", "تقرير PDF", "نزّل PDF", "حمّل PDF",
            "أريد التقرير", "ابغى التقرير",
            "هل يمكنك ان تقوم بتنزيل الملف",
            "ممكن تنزل التقرير", "ارسل لي ملف التقرير",
        ]:
            assert wants_pdf(phrase), f"Arabic phrase should trigger PDF: {phrase}"

    def test_wants_pdf_english_still_works(self):
        from protectme_agent.fast_path import wants_pdf
        for phrase in ["download the PDF", "generate a PDF report",
                       "can you export the report", "make me a pdf"]:
            assert wants_pdf(phrase), f"English phrase should trigger PDF: {phrase}"

    def test_wants_pdf_ignores_normal_questions(self):
        from protectme_agent.fast_path import wants_pdf
        for phrase in ["what is the biggest risk?", "اشرح لي البند الأول",
                       "should I sign this?", "ما هو أكبر خطر؟"]:
            assert not wants_pdf(phrase), f"Should NOT trigger PDF: {phrase}"

    # ── handle_turn integration (no Gemini needed for the PDF fast path) ──────
    def _mock_client(self):
        mock = MagicMock()
        mock.conversation_model = "gemini-3.5-flash"
        mock.voice_fallback_model = "gemini-3.1-flash-lite"

        async def _stream(*a, **k):
            yield "..."
        mock.stream = _stream
        return mock

    def _run(self, user_text, language="ar"):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(self._mock_client())
        session = Session(risk_report=REPORT, language=language)

        async def _collect():
            return [e async for e in agent.handle_turn(user_text, session)]

        return asyncio.run(_collect())

    def _said(self, events):
        return " ".join(e["text"] for e in events if e["type"] == "sentence")

    def test_arabic_download_file_triggers_download_event(self):
        events = self._run("تنزيل الملف")
        assert any(e["type"] == "download_pdf" for e in events)

    def test_arabic_polite_question_triggers_download_event(self):
        events = self._run("هل يمكنك ان تقوم بتنزيل الملف")
        assert any(e["type"] == "download_pdf" for e in events)

    def test_arabic_download_message_is_arabic(self):
        events = self._run("حمّل لي تقرير PDF")
        dl = [e for e in events if e["type"] == "download_pdf"]
        assert dl, "expected a download_pdf event"
        # Spoken confirmation is Arabic ("تم تجهيز تقرير PDF لك.")
        assert "تجهيز" in self._said(events)

    def test_english_download_pdf_still_triggers_event(self):
        events = self._run("download the PDF report", language="en")
        assert any(e["type"] == "download_pdf" for e in events)
        assert "PDF" in self._said(events)  # English confirmation
