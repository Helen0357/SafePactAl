"""
Phase 8I-i18n — language propagation + Arabic-aware behavior tests.

  • X-Language header → analysis runs in Arabic + session.language stored
  • analysis prompt carries the Arabic instruction only for ar
  • voice WS ?language=ar → session.language set to 'ar'
  • Arabic session → English question answered in Arabic by default
  • explicit "in English" overrides an Arabic session
  • English session unchanged
  • PDF endpoint honors X-Language: ar

Gemini/TTS mocked — fast, no quota.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── fast_path language helpers ─────────────────────────────────────────────────

class TestLanguageHelpers:
    def test_normalize_language(self):
        from protectme_agent.fast_path import normalize_language
        assert normalize_language("ar") == "ar"
        assert normalize_language("AR-sa") == "ar"
        assert normalize_language("en") == "en"
        assert normalize_language("") == "en"
        assert normalize_language(None) == "en"

    def test_resolve_response_language(self):
        from protectme_agent.fast_path import resolve_response_language as r
        assert r("what is the biggest risk?", "ar") == "ar"      # ar session
        assert r("what is the biggest risk?", "en") == "en"      # en session
        assert r("explain in English please", "ar") == "en"      # explicit en wins
        assert r("اشرح بالعربي", "en") == "ar"                    # explicit ar wins


# ── analysis prompt ────────────────────────────────────────────────────────────

class TestAnalysisPrompt:
    def test_arabic_instruction_present_only_for_ar(self):
        from protectme_agent.prompts.contract_analysis_prompt import build_analysis_prompt
        ar = build_analysis_prompt("contract", language="ar")
        en = build_analysis_prompt("contract", language="en")
        assert "Arabic" in ar and "العربية" in ar
        assert "overall_risk" in ar  # enums stay English instruction
        assert "Arabic" not in en


# ── analyze endpoint X-Language ────────────────────────────────────────────────

class TestAnalyzeLanguage:
    def test_x_language_ar_reaches_orchestrator_and_session(self):
        with patch("app.services.contract_service._get_orchestrator") as mock_build:
            mock_orch = MagicMock()
            mock_orch.analyze_contract = AsyncMock(return_value=REPORT)
            mock_build.return_value = mock_orch
            resp = client.post("/api/contracts/analyze", data={"text": "x"},
                               headers={"X-Language": "ar"})
        assert resp.status_code == 200
        # orchestrator received language=ar
        assert mock_orch.analyze_contract.call_args.kwargs.get("language") == "ar"
        # session stored language=ar
        sid = resp.json()["session_id"]
        assert client.get(f"/api/session/{sid}").json()["language"] == "ar"

    def test_default_language_is_en(self):
        with patch("app.services.contract_service._get_orchestrator") as mock_build:
            mock_orch = MagicMock()
            mock_orch.analyze_contract = AsyncMock(return_value=REPORT)
            mock_build.return_value = mock_orch
            resp = client.post("/api/contracts/analyze", data={"text": "x"})
        assert mock_orch.analyze_contract.call_args.kwargs.get("language") == "en"


# ── voice WS language query param ──────────────────────────────────────────────

class TestVoiceWsLanguage:
    def _patch_voice(self):
        async def _handle_turn(user_text, session):
            yield {"type": "status", "state": "idle", "label": "Ready"}
        mock_agent = MagicMock()
        mock_agent.handle_turn = _handle_turn
        return (
            patch("app.services.voice_service.ConversationAgent", MagicMock(return_value=mock_agent)),
            patch("app.services.voice_service._build_gemini_client"),
            patch("app.services.voice_service.synthesize_speech_fast", AsyncMock(return_value=None)),
        )

    def test_ws_language_param_sets_session_language(self):
        s = Session(risk_report=REPORT)
        session_repository.create(s)
        p1, p2, p3 = self._patch_voice()
        with p1, p2, p3:
            with client.websocket_connect(f"/ws/voice/{s.session_id}?language=ar") as ws:
                ws.receive_json()  # status
                ws.receive_json()  # greeting
        assert session_repository.get(s.session_id).language == "ar"


# ── conversation agent language behavior ───────────────────────────────────────

class TestAgentLanguage:
    def _mock_client(self):
        mock = MagicMock()
        mock.conversation_model = "gemini-3.5-flash"
        mock.voice_fallback_model = "gemini-3.1-flash-lite"

        async def _stream(*a, **k):
            yield "هذا هو الجواب."
        mock.stream = _stream
        return mock

    async def _collect(self, agen):
        return [e async for e in agen]

    def _debug(self, events):
        return " ".join(e["log"] for e in events if e["type"] == "debug")

    def _said(self, events):
        return " ".join(e["text"] for e in events if e["type"] == "sentence")

    def test_arabic_session_answers_arabic_for_english_question(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(self._mock_client())
        session = Session(risk_report=REPORT, language="ar")
        events = asyncio.run(self._collect(agent.handle_turn("what is the biggest risk?", session)))
        assert "[Arabic] lang=ar" in self._debug(events)

    def test_english_session_unchanged(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(self._mock_client())
        session = Session(risk_report=REPORT, language="en")
        events = asyncio.run(self._collect(agent.handle_turn("what is the biggest risk?", session)))
        assert "[Arabic]" not in self._debug(events)
        assert "Deposit Forfeiture" in self._said(events)  # English deterministic fast path

    def test_explicit_english_overrides_arabic_session(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(self._mock_client())
        session = Session(risk_report=REPORT, language="ar")
        events = asyncio.run(self._collect(
            agent.handle_turn("explain the biggest risk in English", session)
        ))
        assert "[Arabic]" not in self._debug(events)


# ── PDF language ───────────────────────────────────────────────────────────────

class TestPdfLanguage:
    def test_pdf_endpoint_arabic_header(self):
        s = Session(risk_report=REPORT, language="ar")
        session_repository.create(s)
        resp = client.post("/api/reports/download-pdf", json={"session_id": s.session_id},
                           headers={"X-Language": "ar"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.content[:5] == b"%PDF-"

    def test_generate_arabic_pdf_valid(self):
        from app.services.report_service import generate_risk_report_pdf
        ar_report = dict(REPORT, contract_type="اتفاقية إيجار", summary="ملخّص عربي")
        pdf = generate_risk_report_pdf(ar_report, language="ar")
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 800
