"""
Phase 5 — Live Gemini streaming validation.
Run from backend/ directory:
  python test_live_streaming.py

Tests:
  1. Real Gemini streaming via GeminiClient.stream()
  2. SentenceBuffer emitting sentences from a real stream
  3. ConversationAgent._handle_general() with a real Q&A prompt
  4. ConversationAgent explain_clause path with ExplainClauseTool
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_AGENT_ROOT = Path(__file__).resolve().parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
import os

API_KEY = os.getenv("GEMINI_API_KEY", "")
CONV_MODEL = os.getenv("GEMINI_CONVERSATION_MODEL", "gemini-2.5-flash")

if not API_KEY:
    print("ERROR: GEMINI_API_KEY not set in backend/.env")
    sys.exit(1)

print(f"API key : set")
print(f"Model   : {CONV_MODEL}")

from protectme_agent.gemini_client import GeminiClient
from protectme_agent.streaming.sentence_buffer import SentenceBuffer
from protectme_agent.conversation_agent import ConversationAgent
from protectme_agent.schemas.intent_schema import Intent, IntentResult

SAMPLE_RISK_REPORT = {
    "contract_type": "Rental Agreement",
    "overall_risk": "High",
    "final_recommendation": "Do Not Sign Yet",
    "summary": "Multiple unfair clauses.",
    "confidence": 0.95,
    "risks": [
        {
            "id": "risk_001",
            "title": "Automatic Lease Renewal",
            "severity": "High",
            "category": "Renewal",
            "clause_text": "The lease shall automatically renew unless 90 days notice is given.",
            "simple_explanation": "Lease renews automatically if you don't give 90 days notice.",
            "why_it_matters": "You could be locked in for another year without realising it.",
            "question_to_ask": "Can the notice period be reduced?",
            "suggested_action": "Negotiate",
        }
    ],
    "missing_information": [],
    "recommended_questions": [],
}


class _MockSession:
    def __init__(self, active_clause_id=None):
        self.risk_report = SAMPLE_RISK_REPORT
        self.active_clause_id = active_clause_id
        self.conversation_history = []


def _make_client():
    return GeminiClient(
        api_key=API_KEY,
        analysis_model=CONV_MODEL,
        conversation_model=CONV_MODEL,
        live_model="",
    )


def _sep(title):
    print(f"\n{'='*55}")
    print(f"  {title}")
    print("="*55)


# ── Test 1: raw stream + SentenceBuffer ──────────────────────────────────────

async def test_sentence_buffer_with_real_stream():
    _sep("Test 1: GeminiClient.stream() + SentenceBuffer")
    client = _make_client()
    buf = SentenceBuffer()
    sentences = []
    chunks = 0

    print("Prompt: 'Give me two short facts about rental contracts.'")
    async for chunk in client.stream(
        prompt="Give me two short facts about rental contracts.",
        temperature=0.1,
    ):
        chunks += 1
        for sentence in buf.add_token(chunk):
            sentences.append(sentence)
            print(f"  [sentence] {sentence[:90]}")

    for sentence in buf.flush():
        sentences.append(sentence)
        print(f"  [flush]    {sentence[:90]}")

    print(f"\n  Chunks received : {chunks}")
    print(f"  Sentences emitted: {len(sentences)}")
    assert chunks > 0, "No chunks received from Gemini stream"
    assert len(sentences) > 0, "SentenceBuffer emitted no sentences"
    print("  RESULT: PASSED")
    return True


# ── Test 2: ConversationAgent general Q&A ────────────────────────────────────

async def test_conversation_agent_qa():
    _sep("Test 2: ConversationAgent._handle_general() (ask_question)")
    client = _make_client()
    agent = ConversationAgent(client)

    mock_router = MagicMock()
    mock_router.route = AsyncMock(return_value=IntentResult(
        intent=Intent.ASK_QUESTION,
        confidence=0.9,
    ))
    agent._router = mock_router

    session = _MockSession()
    events = []

    async for event in agent.handle_turn(
        "What is the biggest risk in this contract?", session
    ):
        events.append(event)
        etype = event["type"]
        if etype == "sentence":
            print(f"  [sentence] {event['text'][:90]}")
        elif etype == "status":
            print(f"  [status]   state={event['state']}")
        elif etype == "debug":
            print(f"  [debug]    {event['log'][:60]}")

    sentences = [e for e in events if e["type"] == "sentence"]
    statuses  = [e for e in events if e["type"] == "status"]
    final     = statuses[-1] if statuses else {}

    print(f"\n  Total events  : {len(events)}")
    print(f"  Sentence events: {len(sentences)}")
    print(f"  Final status   : {final.get('state', 'none')}")
    assert len(sentences) > 0, "No sentence events from ConversationAgent"
    assert final.get("state") == "idle", "Final status should be 'idle'"
    print("  RESULT: PASSED")
    return True


# ── Test 3: ConversationAgent explain_clause ─────────────────────────────────

async def test_conversation_agent_explain_clause():
    _sep("Test 3: ConversationAgent._handle_explain_clause() (real ExplainClauseTool)")
    client = _make_client()
    agent = ConversationAgent(client)

    mock_router = MagicMock()
    mock_router.route = AsyncMock(return_value=IntentResult(
        intent=Intent.EXPLAIN_CLAUSE,
        confidence=0.92,
        target_clause_ids=["risk_001"],
    ))
    agent._router = mock_router

    session = _MockSession()
    events = []

    async for event in agent.handle_turn("Explain the renewal clause", session):
        events.append(event)
        etype = event["type"]
        if etype == "sentence":
            print(f"  [sentence] {event['text'][:90]}")
        elif etype == "status":
            print(f"  [status]   state={event['state']}")
        elif etype == "debug":
            print(f"  [debug]    {event['log'][:60]}")

    sentences = [e for e in events if e["type"] == "sentence"]
    statuses  = [e for e in events if e["type"] == "status"]
    final     = statuses[-1] if statuses else {}

    print(f"\n  Total events  : {len(events)}")
    print(f"  Sentence events: {len(sentences)}")
    print(f"  Final status   : {final.get('state', 'none')}")
    assert len(sentences) > 0, "No sentence events from explain_clause handler"
    assert final.get("state") == "idle", "Final status should be 'idle'"
    print("  RESULT: PASSED")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print("\nProtectMe AI — Phase 5 Live Streaming Validation")
    results = {}

    for name, coro in [
        ("sentence_buffer_stream", test_sentence_buffer_with_real_stream()),
        ("conversation_agent_qa", test_conversation_agent_qa()),
        ("conversation_agent_explain", test_conversation_agent_explain_clause()),
    ]:
        try:
            results[name] = await coro
        except AssertionError as exc:
            print(f"\n  FAILED: {exc}")
            results[name] = False
        except Exception as exc:
            print(f"\n  ERROR: {type(exc).__name__}: {exc}")
            results[name] = False

    _sep("Summary")
    for name, passed in results.items():
        label = "PASSED" if passed else "FAILED"
        print(f"  [{label}] {name}")

    total = len(results)
    passed = sum(results.values())
    print(f"\n  {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
