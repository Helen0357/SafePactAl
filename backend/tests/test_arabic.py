"""
Phase 8H — Arabic voice/language support tests.

Covers:
  1. Arabic biggest-risk intent           → routes Arabic, intent=biggest_risk
  2. Arabic explain active clause          → routes Arabic, intent=explain, uses active clause
  3. English request "explain in Arabic"   → response language = Arabic
  4. Arabic should-I-sign question         → routes Arabic, intent=should_i_sign
  5. Arabic generate WhatsApp message      → draft_ready, format=whatsapp, Arabic instruction
  6. Arabic voice selection / fallback     → _voice_for behavior
  7. English mode remains unchanged        → detect_language='en', English fast path

All Gemini/TTS calls are mocked — fast, no real quota.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_AGENT_ROOT = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

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
        {"id": "risk_002", "title": "Early Termination Penalty", "severity": "Medium",
         "category": "Termination", "clause_text": "3 months rent penalty for early exit.",
         "simple_explanation": "Leaving early costs 3 months rent.",
         "why_it_matters": "A large unexpected cost.",
         "question_to_ask": "Can the penalty be reduced?", "suggested_action": "Negotiate"},
    ],
    "missing_information": [],
    "recommended_questions": ["What is the refund policy?"],
}


def _session(active_clause_id=None):
    return Session(risk_report=REPORT, active_clause_id=active_clause_id)


def _mock_client():
    """Client whose stream() yields Arabic text and generate() returns an Arabic draft."""
    mock = MagicMock()
    mock.conversation_model = "gemini-2.5-flash"
    mock.voice_fallback_model = "gemini-2.5-flash-lite"

    async def _stream(*args, **kwargs):
        for chunk in ["هذا البند يعني التزامًا ماليًا عليك. ", "المشكلة أن الغرامة قد تكون كبيرة. "]:
            yield chunk

    mock.stream = _stream
    mock.generate = AsyncMock(return_value="مرحباً، لدي بعض الملاحظات حول العقد. [اسمك]")
    return mock


async def _collect(agen):
    return [e async for e in agen]


def _debug(events):
    return " ".join(e["log"] for e in events if e["type"] == "debug")


def _sentences(events):
    return " ".join(e["text"] for e in events if e["type"] == "sentence")



class TestArabicDetection:
    def test_detect_language_arabic_script(self):
        from protectme_agent.fast_path import detect_language
        assert detect_language("ما أكبر خطر في العقد؟") == "ar"

    def test_detect_language_english_request(self):
        from protectme_agent.fast_path import detect_language
        assert detect_language("Explain this clause in Arabic") == "ar"

    def test_detect_language_plain_english(self):
        from protectme_agent.fast_path import detect_language
        assert detect_language("What is the biggest risk?") == "en"

    def test_match_arabic_intents(self):
        from protectme_agent.fast_path import (
            match_arabic_intent, BIGGEST_RISK, EXPLAIN_CLAUSE,
            SHOULD_I_SIGN, WHAT_TO_ASK, GENERATE_MESSAGE,
        )
        assert match_arabic_intent("ما أكبر خطر في العقد؟") == BIGGEST_RISK
        assert match_arabic_intent("اشرح هذا البند") == EXPLAIN_CLAUSE
        assert match_arabic_intent("هل أوقع العقد؟") == SHOULD_I_SIGN
        assert match_arabic_intent("ماذا أسأل قبل التوقيع؟") == WHAT_TO_ASK
        assert match_arabic_intent("اكتب لي رسالة واتساب قصيرة") == GENERATE_MESSAGE

    def test_arabic_message_format(self):
        from protectme_agent.fast_path import detect_message_format, message_extra_instruction
        assert detect_message_format("اكتب لي رسالة واتساب") == "whatsapp"
        assert detect_message_format("اكتب لي إيميل") == "email"
        assert message_extra_instruction("اكتب رسالة قصيرة") == "Make it short and concise."



class TestArabicRouting:
    def test_arabic_biggest_risk(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(agent.handle_turn("ما أكبر خطر في العقد؟", _session())))
        assert "[Arabic] lang=ar intent=biggest_risk" in _debug(events)
        assert _sentences(events).strip()  

    def test_arabic_explain_active_clause(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(
            agent.handle_turn("اشرح لي هذا البند", _session(active_clause_id="risk_001"))
        ))
        assert "[Arabic] lang=ar intent=explain_active_clause" in _debug(events)
        assert _sentences(events).strip()

    def test_english_request_explain_in_arabic(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(
            agent.handle_turn("Explain this clause in Arabic", _session(active_clause_id="risk_001"))
        ))
        assert "[Arabic] lang=ar" in _debug(events)
        assert "intent=explain_active_clause" in _debug(events)

    def test_arabic_should_i_sign(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(agent.handle_turn("هل أوقع العقد؟", _session())))
        assert "[Arabic] lang=ar intent=should_i_sign" in _debug(events)
        assert _sentences(events).strip()

    def test_arabic_generate_whatsapp(self):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(
            agent.handle_turn("اكتب لي رسالة واتساب قصيرة", _session(active_clause_id="risk_001"))
        ))
        debug = _debug(events)
        assert "[Arabic] lang=ar intent=generate_message" in debug
        assert "format=whatsapp" in debug
        assert any(e["type"] == "draft_ready" for e in events)

    def test_english_mode_unchanged(self):
        """Plain English still detects 'en' and uses the deterministic English path."""
        from protectme_agent.conversation_agent import ConversationAgent
        from protectme_agent.fast_path import detect_language
        assert detect_language("What is the biggest risk?") == "en"
        agent = ConversationAgent(_mock_client())
        events = asyncio.run(_collect(agent.handle_turn("What is the biggest risk?", _session())))
        said = _sentences(events)
        assert "Deposit Forfeiture" in said
        assert "[Arabic]" not in _debug(events)



class TestArabicVoiceSelection:
    def test_uses_configured_arabic_voice(self, monkeypatch):
        from app.services import voice_service as vs
        from app.core.config import settings
        monkeypatch.setattr(settings, "google_cloud_tts_arabic_voice", "ar-XA-Wavenet-B")
        monkeypatch.setattr(settings, "google_cloud_tts_arabic_language", "ar-XA")
        voice, lang = vs._voice_for("هذا نص عربي", "en-US-Journey-D")
        assert voice == "ar-XA-Wavenet-B"
        assert lang == "ar-XA"

    def test_fallback_when_unconfigured(self, monkeypatch):
        from app.services import voice_service as vs
        from app.core.config import settings
        monkeypatch.setattr(settings, "google_cloud_tts_arabic_voice", "")
        monkeypatch.setattr(settings, "google_cloud_tts_arabic_language", "ar-XA")
        vs._arabic_fallback_warned = False
        voice, lang = vs._voice_for("هذا نص عربي", "en-US-Journey-D")
        assert voice == ""       
        assert lang == "ar-XA"

    def test_english_voice_unchanged(self, monkeypatch):
        from app.services import voice_service as vs
        from app.core.config import settings
        monkeypatch.setattr(settings, "google_cloud_tts_language", "en-US")
        voice, lang = vs._voice_for("This is an English sentence.", "en-US-Journey-D")
        assert voice == "en-US-Journey-D"
        assert lang == "en-US"
