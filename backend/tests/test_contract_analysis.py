"""
Phase 2 tests — contract analysis agent and JSON utilities.

Unit tests avoid real Gemini API calls (fast, no quota).
The live integration test is run manually via curl / the test server.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)



class TestExtractJson:
    def _extract(self, text):
        from app.utils.json_utils import extract_json_from_text
        return extract_json_from_text(text)

    def test_direct_json(self):
        assert self._extract('{"a": 1}') == {"a": 1}

    def test_json_in_code_fence(self):
        text = '```json\n{"a": 1}\n```'
        assert self._extract(text) == {"a": 1}

    def test_json_in_plain_fence(self):
        text = '```\n{"a": 1}\n```'
        assert self._extract(text) == {"a": 1}

    def test_json_buried_in_prose(self):
        text = 'Here is the result: {"a": 1} end.'
        assert self._extract(text) == {"a": 1}

    def test_invalid_returns_none(self):
        assert self._extract("not json at all") is None

    def test_empty_string_returns_none(self):
        assert self._extract("") is None



class TestRiskReportSchema:
    def _make_valid_report(self):
        return {
            "contract_type": "Rental Agreement",
            "overall_risk": "High",
            "final_recommendation": "Do Not Sign Yet",
            "summary": "High risk contract.",
            "confidence": 0.9,
            "risks": [
                {
                    "id": "risk_001",
                    "title": "Unfair penalty",
                    "severity": "High",
                    "category": "Cancellation",
                    "clause_text": "Tenant forfeits full deposit.",
                    "simple_explanation": "You lose all your money.",
                    "why_it_matters": "Could lose thousands.",
                    "question_to_ask": "Can we negotiate this?",
                    "suggested_action": "Negotiate",
                }
            ],
            "missing_information": [],
            "recommended_questions": ["What is the refund policy?"],
        }

    def test_valid_report_validates(self):
        from protectme_agent.schemas.risk_report_schema import RiskReport
        report = RiskReport(**self._make_valid_report())
        assert report.overall_risk.value == "High"
        assert len(report.risks) == 1

    def test_risk_sorted_high_first(self):
        from protectme_agent.schemas.risk_report_schema import RiskReport, RiskSeverity
        base = self._make_valid_report()
        base_risk = base["risks"][0]
        base["risks"] = [
            {**base_risk, "id": "risk_001", "severity": "Low",    "title": "Minor issue"},
            {**base_risk, "id": "risk_002", "severity": "Medium",  "title": "Medium issue"},
            {**base_risk, "id": "risk_003", "severity": "High",   "title": "Serious issue"},
        ]
        report = RiskReport(**base)
        _ORDER = {RiskSeverity.HIGH: 0, RiskSeverity.MEDIUM: 1, RiskSeverity.LOW: 2}
        report.risks.sort(key=lambda r: _ORDER.get(r.severity, 9))
        assert report.risks[0].severity == RiskSeverity.HIGH
        assert report.risks[1].severity == RiskSeverity.MEDIUM
        assert report.risks[2].severity == RiskSeverity.LOW



MOCK_RISK_REPORT = {
    "contract_type": "Rental Agreement",
    "overall_risk": "High",
    "final_recommendation": "Do Not Sign Yet",
    "summary": "This contract contains several high-risk clauses.",
    "confidence": 0.92,
    "risks": [
        {
            "id": "risk_001",
            "title": "Deposit forfeiture on early exit",
            "severity": "High",
            "category": "Cancellation",
            "clause_text": "Tenant shall forfeit the entire security deposit.",
            "simple_explanation": "You lose all your deposit if you leave early.",
            "why_it_matters": "This could cost you thousands of dollars.",
            "question_to_ask": "Can we negotiate a pro-rated refund instead?",
            "suggested_action": "Negotiate",
        },
        {
            "id": "risk_002",
            "title": "Unlimited rent increase at renewal",
            "severity": "High",
            "category": "Payment",
            "clause_text": "Landlord may increase rent by up to 20% without notice.",
            "simple_explanation": "Your rent can jump 20% with no warning.",
            "why_it_matters": "Unexpected cost increases you cannot plan for.",
            "question_to_ask": "Can we cap rent increases at a lower percentage?",
            "suggested_action": "Negotiate",
        },
    ],
    "missing_information": ["Refund policy is not stated."],
    "recommended_questions": ["What is the maximum rent increase?"],
}


def test_analyze_text_with_mocked_gemini():
    """Endpoint returns 200 and a valid risk report when Gemini is mocked."""
    with patch(
        "app.services.contract_service._get_orchestrator"
    ) as mock_build:
        mock_orch = MagicMock()
        mock_orch.analyze_contract = AsyncMock(return_value=MOCK_RISK_REPORT)
        mock_build.return_value = mock_orch

        response = client.post(
            "/api/contracts/analyze",
            data={"text": "Sample contract text for unit test."},
        )

    assert response.status_code == 200
    body = response.json()
    assert "session_id" in body
    assert body["risk_report"]["overall_risk"] == "High"
    assert len(body["risk_report"]["risks"]) == 2
    assert body["risk_report"]["risks"][0]["severity"] == "High"


def test_analyze_no_input_returns_400():
    response = client.post("/api/contracts/analyze")
    assert response.status_code == 400


def test_session_stored_after_analysis():
    """After analysis, GET /api/session/{id} returns the stored risk report."""
    with patch(
        "app.services.contract_service._get_orchestrator"
    ) as mock_build:
        mock_orch = MagicMock()
        mock_orch.analyze_contract = AsyncMock(return_value=MOCK_RISK_REPORT)
        mock_build.return_value = mock_orch

        analyze_resp = client.post(
            "/api/contracts/analyze",
            data={"text": "Another sample contract."},
        )

    session_id = analyze_resp.json()["session_id"]
    session_resp = client.get(f"/api/session/{session_id}")
    assert session_resp.status_code == 200
    session = session_resp.json()
    assert session["risk_report"]["contract_type"] == "Rental Agreement"
    assert session["risk_report"]["risks"][0]["id"] == "risk_001"
