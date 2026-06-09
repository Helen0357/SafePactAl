"""
Phase 8I — PDF report download tests.

  • POST /api/reports/download-pdf → 200 + application/pdf for a valid session
  • 404 for an unknown session
  • 409 for a session with no analyzed risk_report
  • PDF generation handles missing/blank fields (safe fallbacks, no crash)
  • voice intent "download report"/"اعمل PDF" → a download_pdf event (no Gemini)

PDF is generated in memory; nothing is written to disk.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.session_repository import session_repository
from app.schemas.session_schema import Session

client = TestClient(app)

REPORT = {
    "contract_type": "Residential Lease Agreement",
    "overall_risk": "High",
    "final_recommendation": "Do Not Sign Yet",
    "summary": "Several risky clauses were found.",
    "confidence": 0.9,
    "risks": [
        {"id": "risk_001", "title": "Unlimited Rent Increase", "severity": "High",
         "category": "Payment", "clause_text": "Rent may rise by any amount.",
         "simple_explanation": "Rent can jump with no cap.", "why_it_matters": "Unpredictable cost.",
         "question_to_ask": "Can we cap it?", "suggested_action": "Negotiate"},
        {"id": "risk_002", "title": "Quiet Hours", "severity": "Low",
         "category": "General", "clause_text": "No noise after 10pm.",
         "simple_explanation": "Be quiet at night.", "why_it_matters": "Minor inconvenience.",
         "question_to_ask": "Any exceptions?", "suggested_action": "Review carefully"},
        {"id": "risk_003", "title": "AC Maintenance", "severity": "Medium",
         "category": "Maintenance", "clause_text": "Tenant pays AC upkeep.",
         "simple_explanation": "You pay for AC repairs.", "why_it_matters": "Can be costly.",
         "question_to_ask": "Who pays major repairs?", "suggested_action": "Clarify"},
    ],
    "missing_information": [],
    "recommended_questions": [],
}


def _make_session(report=REPORT) -> str:
    s = Session(risk_report=report)
    session_repository.create(s)
    return s.session_id


# ── Endpoint ──────────────────────────────────────────────────────────────────

class TestPdfEndpoint:
    def test_valid_session_returns_pdf(self):
        sid = _make_session()
        resp = client.post("/api/reports/download-pdf", json={"session_id": sid})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "ProtectMe_AI_Risk_Report.pdf" in resp.headers.get("content-disposition", "")
        assert resp.content[:5] == b"%PDF-"  # valid PDF header
        assert len(resp.content) > 1000

    def test_language_param_accepted(self):
        sid = _make_session()
        resp = client.post("/api/reports/download-pdf", json={"session_id": sid, "language": "ar"})
        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_unknown_session_404(self):
        resp = client.post(
            "/api/reports/download-pdf",
            json={"session_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()

    def test_no_risk_report_409(self):
        s = Session(risk_report=None)
        session_repository.create(s)
        resp = client.post("/api/reports/download-pdf", json={"session_id": s.session_id})
        assert resp.status_code == 409
        assert "no risk report" in resp.text.lower()


# ── PDF generation directly ─────────────────────────────────────────────────────

class TestPdfGeneration:
    def test_generates_valid_pdf(self):
        from app.services.report_service import generate_risk_report_pdf
        pdf = generate_risk_report_pdf(REPORT)
        assert isinstance(pdf, (bytes, bytearray))
        assert pdf[:5] == b"%PDF-"

    def test_handles_missing_fields(self):
        from app.services.report_service import generate_risk_report_pdf
        sparse = {
            "contract_type": "",
            "risks": [
                {"id": "risk_001", "title": "", "severity": "High"},  # most fields missing
                {"id": "risk_002"},  # almost everything missing
            ],
        }
        pdf = generate_risk_report_pdf(sparse)  # must not raise
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 500

    def test_handles_empty_report(self):
        from app.services.report_service import generate_risk_report_pdf
        pdf = generate_risk_report_pdf({})
        assert pdf[:5] == b"%PDF-"

    def test_escapes_markup_chars(self):
        from app.services.report_service import generate_risk_report_pdf
        tricky = {
            "contract_type": "Lease <b>& Co.</b>",
            "summary": "Fees > 10% & <unusual> terms",
            "risks": [{"id": "risk_001", "title": "A & B < C", "severity": "Medium",
                       "clause_text": "x < y & z > 0"}],
        }
        pdf = generate_risk_report_pdf(tricky)  # must not raise on &, <, >
        assert pdf[:5] == b"%PDF-"


# ── Voice intent ─────────────────────────────────────────────────────────────────

class TestVoicePdfIntent:
    def _mock_client(self):
        mock = MagicMock()
        mock.conversation_model = "gemini-3.5-flash"
        mock.voice_fallback_model = "gemini-3.1-flash-lite"
        return mock

    async def _collect(self, agen):
        return [e async for e in agen]

    def _run(self, text):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(self._mock_client())
        session = Session(risk_report=REPORT)
        return asyncio.run(self._collect(agent.handle_turn(text, session)))

    def test_english_download_report(self):
        for phrase in ["download the report as a pdf", "generate PDF",
                       "export report", "give me a file", "make a PDF"]:
            events = self._run(phrase)
            types = [e["type"] for e in events]
            assert "download_pdf" in types, phrase
            assert any(e["type"] == "sentence" for e in events)

    def test_arabic_download_report(self):
        events = self._run("اعمل PDF")
        assert any(e["type"] == "download_pdf" for e in events)

    def test_wants_pdf_detector(self):
        from protectme_agent.fast_path import wants_pdf
        assert wants_pdf("download report")
        assert wants_pdf("can you make a pdf for me")
        assert wants_pdf("حمل التقرير")
        assert not wants_pdf("what is the biggest risk?")
        assert not wants_pdf("explain this clause")
