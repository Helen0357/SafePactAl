"""
Phase 8H-mod-3 tests:
  • generate_message preserves the user's EXACT request + custom details
    (lion/أسد, installments, waive late fee, …) and honors whatsapp/email + Arabic
  • model-aware thinking config (Gemini 3 → thinking_level, Gemini 2.x → budget)
  • TTS chunk split+merge never produces tiny chunks

Gemini is mocked (generate echoes the prompt it receives) — fast, no quota.
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
    "contract_type": "Tenancy Agreement",
    "overall_risk": "High",
    "final_recommendation": "Review Before Signing",
    "summary": "Has a non-refundable pet fee.",
    "confidence": 0.9,
    "risks": [
        {"id": "risk_001", "title": "Non-Refundable Pet Fee", "severity": "Medium",
         "category": "Fees", "clause_text": "A non-refundable pet fee of $500 applies to any animal.",
         "simple_explanation": "You pay $500 for any pet and never get it back.",
         "why_it_matters": "It is an extra cost that is never returned.",
         "question_to_ask": "Can the pet fee be waived or reduced?", "suggested_action": "Negotiate"},
        {"id": "risk_002", "title": "Large Security Deposit", "severity": "High",
         "category": "Deposit", "clause_text": "A deposit of $3000 is required.",
         "simple_explanation": "A big deposit is held.",
         "why_it_matters": "Ties up a lot of your money.",
         "question_to_ask": "Can the deposit be paid in installments?", "suggested_action": "Negotiate"},
    ],
    "missing_information": [],
    "recommended_questions": [],
}


def _session(active="risk_001", selected=None):
    return Session(risk_report=REPORT, active_clause_id=active, selected_clause_ids=selected or [])


def _echo_client():
    """generate() returns the prompt it was given, so tests can assert the prompt
    carried the user's request/details."""
    mock = MagicMock()
    mock.conversation_model = "gemini-3.5-flash"
    mock.voice_fallback_model = "gemini-3.1-flash-lite"
    mock.generate = AsyncMock(side_effect=lambda **kw: kw.get("prompt", ""))
    return mock


async def _collect(agen):
    return [e async for e in agen]


def _draft(events):
    e = next((x for x in events if x["type"] == "draft_ready"), None)
    return e["draft"] if e else ""


def _debug(events):
    return " ".join(x["log"] for x in events if x["type"] == "debug")


# ── P1: custom details preserved ──────────────────────────────────────────────

class TestMessageCustomDetails:
    def _run(self, text, active="risk_001"):
        from protectme_agent.conversation_agent import ConversationAgent
        agent = ConversationAgent(_echo_client())
        return asyncio.run(_collect(agent.handle_turn(text, _session(active=active))))

    def test_arabic_whatsapp_lion_waiver(self):
        events = self._run(
            "اكتب لي رسالة واتساب قصيرة، قل له لدي أسد، هل يمكن إعفاء الأسد من هذه الرسوم؟"
        )
        draft = _draft(events)
        debug = _debug(events)
        assert "format=whatsapp" in debug
        assert "lang=ar" in debug
        assert "أسد" in draft  # the lion detail is carried into the prompt
        assert "إعفاء" in draft or "هذه الرسوم" in draft  # the waiver ask is carried
        assert "WhatsApp" in draft

    def test_english_whatsapp_installments(self):
        events = self._run(
            "write a whatsapp message asking if I can pay the deposit in two installments",
            active="risk_002",
        )
        draft = _draft(events)
        assert "format=whatsapp" in _debug(events)
        assert "two installments" in draft

    def test_english_email_remove_late_fee(self):
        events = self._run(
            "write a formal email asking them to remove the late fee completely"
        )
        draft = _draft(events)
        assert "format=email" in _debug(events)
        assert "late fee" in draft

    def test_request_is_passed_verbatim(self):
        events = self._run("write a short whatsapp telling him my company will guarantee the rent")
        draft = _draft(events)
        assert "company will guarantee the rent" in draft


# ── P5: model-aware thinking config ───────────────────────────────────────────

class TestThinkingConfig:
    @staticmethod
    def _level(tc):
        lvl = getattr(tc, "thinking_level", None)
        return str(getattr(lvl, "value", lvl) or "").upper()

    def test_gemini3_uses_thinking_level(self):
        from protectme_agent.gemini_client import GeminiClient
        tc = GeminiClient._thinking_config("gemini-3.5-flash")
        assert self._level(tc) == "MINIMAL"
        assert getattr(tc, "thinking_budget", None) is None

    def test_gemini3_flash_lite_uses_level(self):
        from protectme_agent.gemini_client import GeminiClient
        tc = GeminiClient._thinking_config("gemini-3.1-flash-lite")
        assert self._level(tc) == "MINIMAL"

    def test_gemini25_uses_budget(self):
        from protectme_agent.gemini_client import GeminiClient
        tc = GeminiClient._thinking_config("gemini-2.5-flash")
        assert getattr(tc, "thinking_budget", None) == 0
        assert self._level(tc) in ("", "NONE")


# ── P4: chunk split + merge ───────────────────────────────────────────────────

class TestChunkMerge:
    def test_no_tiny_chunks(self):
        from app.services.voice_service import _chunk_for_tts, _TTS_MIN_CHARS
        text = (
            "This clause means you pay a non-refundable fee. It matters. "
            "Ask them. You could negotiate."
        )
        chunks = _chunk_for_tts(text)
        if len(chunks) > 1:
            assert all(len(c) >= _TTS_MIN_CHARS for c in chunks), chunks

    def test_merge_small_folds_fragments(self):
        from app.services.voice_service import _merge_small
        merged = _merge_small(["Hi.", "This is a longer fragment of text here.", "ok."])
        assert all(len(c) >= 20 for c in merged) or len(merged) == 1

    def test_long_text_splits_under_max(self):
        from app.services.voice_service import _chunk_for_tts, _TTS_MAX_CHARS
        text = " ".join(["word"] * 120)  # ~600 chars
        chunks = _chunk_for_tts(text)
        assert len(chunks) >= 2
        assert all(len(c) <= _TTS_MAX_CHARS + 40 for c in chunks)  # allow merge slack
