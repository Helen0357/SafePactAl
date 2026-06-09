"""
Final pre-Phase-9 bugfix tests.

Covers:
  1/2. why_it_matters + all-field normalization (RiskReport validator).
  3.   WhatsApp vs email format parsing + "make it short" instruction.
  4.   Severity-specific query routing ("the low risk", "first high risk").
  5.   Clause / risk number mapping ("clause 6" -> risk_006).
  7.   Per-chunk TTS timeout (one slow chunk never blocks the turn).

All Gemini/TTS calls are mocked or avoided — fast, no real quota.
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

import pytest

from app.schemas.session_schema import Session


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
         "why_it_matters": "You could lose thousands of dollars.",
         "question_to_ask": "Can we pro-rate the refund?", "suggested_action": "Negotiate"},
        {"id": "risk_002", "title": "Unlimited Rent Increase", "severity": "High",
         "category": "Payment", "clause_text": "Rent may rise by any amount.",
         "simple_explanation": "Your rent can jump with no cap.",
         "why_it_matters": "Costs you cannot plan for.",
         "question_to_ask": "Can we cap increases?", "suggested_action": "Negotiate"},
        {"id": "risk_003", "title": "Air-Conditioner Maintenance Costs", "severity": "Medium",
         "category": "Maintenance", "clause_text": "Tenant pays all AC maintenance.",
         "simple_explanation": "You pay for all AC repairs.",
         "why_it_matters": "Repairs can be expensive.",
         "question_to_ask": "Who pays for major repairs?", "suggested_action": "Clarify"},
        {"id": "risk_004", "title": "Quiet Hours", "severity": "Low",
         "category": "General", "clause_text": "Quiet hours after 10pm.",
         "simple_explanation": "No noise after 10pm.",
         "why_it_matters": "Minor lifestyle limitation.",
         "question_to_ask": "Are there exceptions?", "suggested_action": "Review carefully"},
        {"id": "risk_005", "title": "Guest Policy", "severity": "Low",
         "category": "General", "clause_text": "Guests limited to 14 days.",
         "simple_explanation": "Guests can only stay 14 days.",
         "why_it_matters": "Could be inconvenient for visitors.",
         "question_to_ask": "Can this be extended?", "suggested_action": "Review carefully"},
        {"id": "risk_006", "title": "Short Notice Period", "severity": "Medium",
         "category": "Termination", "clause_text": "Only 7 days notice to vacate.",
         "simple_explanation": "Landlord can ask you to leave in 7 days.",
         "why_it_matters": "Little time to find a new home.",
         "question_to_ask": "Can the notice period be longer?", "suggested_action": "Negotiate"},
    ],
    "missing_information": [],
    "recommended_questions": [],
}


def _session(active_clause_id=None, report=REPORT):
    return Session(risk_report=report, active_clause_id=active_clause_id)


async def _collect(agen):
    return [e async for e in agen]


def _sentences(events):
    return " ".join(e["text"] for e in events if e["type"] == "sentence")


def _debug(events):
    return " ".join(e["log"] for e in events if e["type"] == "debug")


def _mock_client():
    mock = MagicMock()
    mock.conversation_model = "gemini-2.5-flash"
    mock.voice_fallback_model = "gemini-2.5-flash-lite"
    mock.generate = AsyncMock(return_value="Subject: Concern\n\nHello, short note. [Your Name]")
    return mock



class TestNormalization:
    def _report_with_blank(self, **overrides):
        from protectme_agent.schemas.risk_report_schema import RiskReport
        risk = {
            "id": "risk_001", "title": "Air-Conditioner Maintenance Costs",
            "severity": "Medium", "category": "Maintenance",
            "clause_text": "Tenant pays all AC maintenance.",
            "simple_explanation": "You pay for AC upkeep.",
            "why_it_matters": "",  
            "question_to_ask": "", "suggested_action": "",
        }
        risk.update(overrides)
        return RiskReport(contract_type="Rental", overall_risk="Medium", risks=[risk])

    def test_blank_why_it_matters_filled(self):
        report = self._report_with_blank()
        why = report.risks[0].why_it_matters
        assert why.strip()
        assert "maintenance" in why.lower() or "repair" in why.lower()

    def test_blank_why_uses_severity_when_no_category_match(self):
        report = self._report_with_blank(category="Miscellaneous",
                                         title="Some odd clause")
        assert report.risks[0].why_it_matters.strip()

    def test_all_required_fields_non_empty(self):
        from protectme_agent.schemas.risk_report_schema import RiskReport
        report = RiskReport(
            contract_type="Rental", overall_risk="High",
            risks=[{"id": "risk_001", "title": "", "severity": "High",
                    "category": "", "clause_text": "", "simple_explanation": "",
                    "why_it_matters": "", "question_to_ask": "", "suggested_action": ""}],
        )
        r = report.risks[0]
        for field in ("title", "category", "clause_text", "simple_explanation",
                      "why_it_matters", "question_to_ask", "suggested_action"):
            assert getattr(r, field).strip(), f"{field} should be non-empty"

    def test_backend_schema_also_normalizes(self):
        from app.schemas.risk_schema import RiskReport as BackendRiskReport
        report = BackendRiskReport(
            contract_type="Rental", overall_risk="Low",
            risks=[{"id": "risk_001", "title": "Deposit terms", "severity": "Low",
                    "category": "Deposit", "why_it_matters": ""}],
        )
        why = report.risks[0].why_it_matters
        assert why.strip()
        assert "money" in why.lower() or "refund" in why.lower()

    def test_existing_values_preserved(self):
        report = self._report_with_blank(why_it_matters="Custom explanation kept.")
        assert report.risks[0].why_it_matters == "Custom explanation kept."



class TestMessageFormatParsing:
    def test_detect_whatsapp(self):
        from protectme_agent.fast_path import detect_message_format
        assert detect_message_format("write a WhatsApp message about this") == "whatsapp"
        assert detect_message_format("send him a whatsapp") == "whatsapp"
        assert detect_message_format("draft a text message") == "whatsapp"

    def test_detect_email(self):
        from protectme_agent.fast_path import detect_message_format
        assert detect_message_format("write a formal email") == "email"
        assert detect_message_format("send an e-mail to the landlord") == "email"

    def test_detect_none_when_unspecified(self):
        from protectme_agent.fast_path import detect_message_format
        assert detect_message_format("write a message about this") is None

    def test_short_instruction(self):
        from protectme_agent.fast_path import message_extra_instruction
        assert message_extra_instruction("make it short") == "Make it short and concise."
        assert message_extra_instruction("keep it brief please") == "Make it short and concise."

    def test_no_instruction_when_neutral(self):
        from protectme_agent.fast_path import message_extra_instruction
        assert message_extra_instruction("write a whatsapp message") is None

    def test_whatsapp_routes_to_whatsapp_format(self):
        """'write WhatsApp message make it short' must generate a short WhatsApp draft."""
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        session = _session(active_clause_id="risk_001")
        events = asyncio.run(_collect(
            agent.handle_turn("write a WhatsApp message about this, make it short", session)
        ))
        debug = _debug(events)
        assert "format=whatsapp" in debug
        assert "Make it short and concise." in debug
        assert any(e["type"] == "draft_ready" for e in events)

    def test_short_message_is_not_treated_as_modify_on_first_generate(self):
        """With no prior draft, a 'write ... short' request still generates."""
        from protectme_agent.fast_path import wants_generate, wants_modify
        text = "write a whatsapp message make it short"
        assert wants_generate(text) is True



class TestSeverityQuery:
    def test_severity_query_detection(self):
        from protectme_agent.fast_path import severity_query
        assert severity_query("explain the low risk") == ("Low", None)
        assert severity_query("the low risks") == ("Low", None)
        assert severity_query("first high risk") == ("High", 1)
        assert severity_query("second low risk") == ("Low", 2)
        assert severity_query("the last medium risk") == ("Medium", -1)

    def test_severity_query_ignores_non_adjacent(self):
        from protectme_agent.fast_path import severity_query
        assert severity_query("give me a high level summary") is None

    def test_two_low_risks_listed_and_asks(self):
        from protectme_agent.fast_path import build_severity_answer
        ans = build_severity_answer(REPORT, "explain the low risk")
        text = ans if isinstance(ans, str) else " ".join(ans)
        assert "2 low-risk items" in text
        assert "Quiet Hours" in text and "Guest Policy" in text
        assert "?" in text 

    def test_never_says_no_low_when_low_exists(self):
        from protectme_agent.fast_path import build_severity_answer
        ans = build_severity_answer(REPORT, "explain the low risk")
        text = (ans if isinstance(ans, str) else " ".join(ans)).lower()
        assert "no low-risk" not in text

    def test_first_high_risk(self):
        from protectme_agent.fast_path import build_severity_answer
        ans = build_severity_answer(REPORT, "explain the first high risk")
        text = ans if isinstance(ans, str) else " ".join(ans)
        assert "Deposit Forfeiture" in text

    def test_last_low_risk(self):
        from protectme_agent.fast_path import build_severity_answer
        ans = build_severity_answer(REPORT, "the last low risk")
        text = ans if isinstance(ans, str) else " ".join(ans)
        assert "Guest Policy" in text

    def test_routing_through_agent(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(
            agent.handle_turn("explain the low risk", _session())
        ))
        said = _sentences(events).lower()
        assert "no low-risk" not in said
        assert "low-risk items" in said
        assert "[FastPath] severity_query" in _debug(events)



class TestClauseNumber:
    def test_parse_digit_forms(self):
        from protectme_agent.fast_path import parse_clause_number
        assert parse_clause_number("explain clause 6") == 6
        assert parse_clause_number("risk 6") == 6
        assert parse_clause_number("risk number 6") == 6
        assert parse_clause_number("clause number 6") == 6

    def test_parse_word_and_ordinal_forms(self):
        from protectme_agent.fast_path import parse_clause_number
        assert parse_clause_number("number six") == 6
        assert parse_clause_number("the sixth risk") == 6
        assert parse_clause_number("explain the last clause") == -1

    def test_severity_query_not_parsed_as_number(self):
        from protectme_agent.fast_path import parse_clause_number
        assert parse_clause_number("explain the low risk") is None
        assert parse_clause_number("second low risk") is None

    def test_resolve_to_risk_006(self):
        from protectme_agent.fast_path import resolve_clause_by_number
        risk = resolve_clause_by_number(REPORT, 6)
        assert risk is not None and risk["id"] == "risk_006"

    def test_clause_6_explained(self):
        from protectme_agent.fast_path import build_clause_number_answer
        ans = build_clause_number_answer(REPORT, "explain clause 6")
        text = ans if isinstance(ans, str) else " ".join(ans)
        assert "Short Notice Period" in text

    def test_missing_clause_reports_not_found(self):
        from protectme_agent.fast_path import build_clause_number_answer
        ans = build_clause_number_answer(REPORT, "explain clause 9")
        text = ans if isinstance(ans, str) else " ".join(ans)
        assert "could not find" in text.lower()
        assert "dashboard" in text.lower()

    def test_routing_through_agent(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(
            agent.handle_turn("explain clause 6", _session(active_clause_id="risk_001"))
        ))
        assert "Short Notice Period" in _sentences(events)
        assert "risk_006" in _debug(events)



class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class TestTtsTimeout:
    def test_slow_chunk_emits_tts_error_without_hanging(self, monkeypatch):
        from app.services import voice_service

        async def _slow_synth(*args, **kwargs):
            await asyncio.sleep(2.0)  
            return b"never-reached"

        monkeypatch.setattr(voice_service, "synthesize_speech_fast", _slow_synth)

        ws = _FakeWS()
        lock = asyncio.Lock()

        async def _run():
            t0 = time.monotonic()
            await voice_service._tts_and_send(
                ws, lock, "This chunk will stall during synthesis.",
                seq=3, turn_id=2, t_turn_start=time.monotonic(),
                emit_error_event=True, gemini_api_key="x",
                timeout_seconds=0.2,
            )
            return time.monotonic() - t0

        elapsed = asyncio.run(_run())
        assert elapsed < 1.5, "timeout should abort the slow chunk quickly"
        errors = [m for m in ws.sent if m.get("type") == "tts_error"]
        assert errors, "a tts_error must be emitted for the timed-out chunk"
        assert errors[0]["seq"] == 3
        assert errors[0]["turn_id"] == 2
        assert "timed out" in errors[0]["message"].lower()

    def test_successful_chunk_sends_audio(self, monkeypatch):
        from app.services import voice_service

        import io, wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(b"\x00\x00" * 1200)
        wav_bytes = buf.getvalue()

        async def _fast_synth(*args, **kwargs):
            return wav_bytes

        monkeypatch.setattr(voice_service, "synthesize_speech_fast", _fast_synth)

        ws = _FakeWS()
        lock = asyncio.Lock()

        asyncio.run(voice_service._tts_and_send(
            ws, lock, "A normal sentence.", seq=0, turn_id=1,
            t_turn_start=time.monotonic(), emit_error_event=True,
            timeout_seconds=5.0,
        ))
        audio = [m for m in ws.sent if m.get("type") == "audio_chunk"]
        assert audio and audio[0]["turn_id"] == 1
        assert not [m for m in ws.sent if m.get("type") == "tts_error"]
