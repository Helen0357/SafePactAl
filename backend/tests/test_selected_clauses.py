"""
Phase 8H bugfix — selected (multiple) clauses tests.

Covers:
  • POST /api/session/selected-clauses stores ids on the session
  • "explain these two clauses" uses ONLY selected_clause_ids (not all risks)
  • "write a message about these" generates for ONLY the selected clauses
  • wants_selected detection (English + Arabic)
  • build_selected_clauses_answer structure

Gemini is mocked — fast, no quota.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
    "summary": "Several risky clauses.",
    "confidence": 0.9,
    "risks": [
        {"id": "risk_001", "title": "Deposit Forfeiture", "severity": "High",
         "category": "Deposit", "clause_text": "Tenant forfeits the full deposit.",
         "simple_explanation": "You lose your whole deposit if you leave early.",
         "why_it_matters": "You could lose thousands.",
         "question_to_ask": "Can we pro-rate?", "suggested_action": "Negotiate"},
        {"id": "risk_002", "title": "Unlimited Rent Increase", "severity": "High",
         "category": "Payment", "clause_text": "Rent may rise by any amount.",
         "simple_explanation": "Rent can jump with no cap.",
         "why_it_matters": "Unpredictable costs.",
         "question_to_ask": "Can we cap it?", "suggested_action": "Negotiate"},
        {"id": "risk_003", "title": "Air-Conditioner Maintenance Costs", "severity": "Medium",
         "category": "Maintenance", "clause_text": "Tenant pays all AC maintenance.",
         "simple_explanation": "You pay for all AC repairs.",
         "why_it_matters": "Repairs can be costly.",
         "question_to_ask": "Who pays major repairs?", "suggested_action": "Clarify"},
    ],
    "missing_information": [],
    "recommended_questions": [],
}


def _session_obj(selected=None):
    return Session(risk_report=REPORT, selected_clause_ids=selected or [])


def _mock_client():
    mock = MagicMock()
    mock.conversation_model = "gemini-2.5-flash"
    mock.voice_fallback_model = "gemini-2.5-flash-lite"
    mock.generate = AsyncMock(return_value="Hi, I have questions about two clauses. [Your Name]")
    return mock


async def _collect(agen):
    return [e async for e in agen]


def _sentences(events):
    return " ".join(e["text"] for e in events if e["type"] == "sentence")


def _debug(events):
    return " ".join(e["log"] for e in events if e["type"] == "debug")


# ── detection / builder units ─────────────────────────────────────────────────

class TestSelectedDetection:
    def test_wants_selected_english(self):
        from protectme_agent.fast_path import wants_selected
        for t in ["explain these clauses", "explain these two", "tell me about both",
                  "compare these clauses", "write a message about these",
                  "explain the selected clauses"]:
            assert wants_selected(t), t

    def test_wants_selected_arabic(self):
        from protectme_agent.fast_path import wants_selected
        assert wants_selected("اشرح هذين البندين")
        assert wants_selected("قارن بين هذين البندين")

    def test_wants_selected_negative(self):
        from protectme_agent.fast_path import wants_selected
        assert not wants_selected("explain this clause")
        assert not wants_selected("what is the biggest risk?")

    def test_builder_uses_only_selected(self):
        from protectme_agent.fast_path import build_selected_clauses_answer
        ans = build_selected_clauses_answer(REPORT, ["risk_001", "risk_003"])
        text = " ".join(ans)
        assert "Deposit Forfeiture" in text
        assert "Air-Conditioner Maintenance Costs" in text
        assert "Unlimited Rent Increase" not in text  # risk_002 excluded
        assert "Together" in text


# ── endpoint ──────────────────────────────────────────────────────────────────

class TestSelectedEndpoint:
    def test_set_selected_clauses_endpoint(self):
        s = Session(risk_report=REPORT)
        session_repository.create(s)
        resp = client.post("/api/session/selected-clauses", json={
            "session_id": s.session_id,
            "selected_clause_ids": ["risk_001", "risk_003"],
        })
        assert resp.status_code == 200
        assert resp.json()["selected_clause_ids"] == ["risk_001", "risk_003"]
        stored = client.get(f"/api/session/{s.session_id}").json()
        assert stored["selected_clause_ids"] == ["risk_001", "risk_003"]


# ── routing through the agent ─────────────────────────────────────────────────

class TestSelectedRouting:
    def test_explain_these_uses_only_selected(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        session = _session_obj(selected=["risk_001", "risk_003"])
        events = asyncio.run(_collect(agent.handle_turn("explain these two clauses", session)))
        said = _sentences(events)
        debug = _debug(events)
        assert "[Voice] selected clauses loaded: risk_001,risk_003" in debug
        assert "[Session] selected_clause_ids retained" in debug
        assert "[FastPath] explain_selected_clauses using risk_001,risk_003" in debug
        assert "Deposit Forfeiture" in said
        assert "Air-Conditioner Maintenance Costs" in said
        assert "Unlimited Rent Increase" not in said  # not selected → not discussed

    def test_followup_reuses_selection(self):
        """A follow-up ('explain them in an easier way') reuses the selection."""
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        session = _session_obj(selected=["risk_001", "risk_003"])
        events = asyncio.run(_collect(
            agent.handle_turn("explain them in an easier way", session)
        ))
        debug = _debug(events)
        said = _sentences(events)
        assert "[FastPath] selected clauses context reused" in debug
        assert "explain_selected_clauses using risk_001,risk_003" in debug
        assert "Deposit Forfeiture" in said and "Air-Conditioner Maintenance Costs" in said
        assert "Unlimited Rent Increase" not in said

    def test_unrelated_question_not_hijacked_by_selection(self):
        """With a selection active, an unrelated specific question is NOT forced
        into the selected-clauses path."""
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        session = _session_obj(selected=["risk_001", "risk_003"])
        events = asyncio.run(_collect(agent.handle_turn("what is the biggest risk?", session)))
        assert "explain_selected_clauses" not in _debug(events)

    def test_write_message_about_these_uses_selected(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        session = _session_obj(selected=["risk_001", "risk_003"])
        events = asyncio.run(_collect(
            agent.handle_turn("write a message about these clauses", session)
        ))
        assert "generate_message using selected risk_001,risk_003" in _debug(events)
        draft = next((e for e in events if e["type"] == "draft_ready"), None)
        assert draft is not None
        tool = next(e for e in events if e.get("type") == "tool_result")
        assert tool["result"]["clause_ids"] == ["risk_001", "risk_003"]

    def test_no_selection_does_not_trigger_selected_path(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        session = _session_obj(selected=[])  # nothing selected
        events = asyncio.run(_collect(agent.handle_turn("explain these two clauses", session)))
        # Without a selection, the selected-clauses fast path must NOT fire.
        assert "explain_selected_clauses" not in _debug(events)
