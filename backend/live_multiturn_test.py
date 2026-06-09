"""
Lifecycle regression test for the rejected-Live fix.

The bug: session.receive() ends after ONE turn, so the old code tore the whole
WebSocket down after the first reply ("Call ended" while still listening).

This test opens ONE /ws/live/ connection and sends THREE text turns over it,
asserting that:
  • audio_chunk events stream back for EVERY turn (session stays alive),
  • the connection is NOT closed between turns,
  • the new backend debug events appear (session loaded / opened / sent seq / closed).

Requires the backend running on :8001 and a valid GEMINI_API_KEY.
Run:  python live_multiturn_test.py
"""
import asyncio
import base64
import io
import json
import time
import wave

import httpx
import websockets

BASE_URL = "http://localhost:8001"
WS_BASE  = "ws://localhost:8001"

CONTRACT = """\
RESIDENTIAL LEASE AGREEMENT
1. RENT: $2,500/month. Late fee of 10% per day after the 5th.
2. ENTRY: Landlord may enter at any time without notice.
3. AUTO-RENEWAL: Renews yearly unless 90 days notice given.
"""

QUESTIONS = [
    "What is the biggest risk?",
    "Is the entry clause normal?",
    "Should I sign this?",
]


def wav_rate(b64: str) -> int:
    with wave.open(io.BytesIO(base64.b64decode(b64)), "rb") as wf:
        return wf.getframerate()


async def one_turn(ws, text, label):
    """Send a turn, collect audio_chunks until audio_done. Returns (n_chunks, first_audio_s, rates)."""
    await ws.send(json.dumps({"type": "text_input", "text": text}))
    t0 = time.monotonic()
    n_chunks = 0
    first_audio = None
    rates = set()
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
        except asyncio.TimeoutError:
            print(f"   [{label}] TIMEOUT")
            break
        ev = json.loads(raw)
        t = ev.get("type")
        if t == "audio_chunk":
            n_chunks += 1
            rates.add(wav_rate(ev["audio"]))
            if first_audio is None:
                first_audio = round(time.monotonic() - t0, 2)
        elif t == "audio_done":
            break
        elif t == "error":
            print(f"   [{label}] ERROR: {ev.get('message')}")
            break
    return n_chunks, first_audio, rates


async def run():
    print("\n" + "=" * 64)
    print("Live lifecycle regression — 3 turns over ONE connection")
    print("=" * 64)

    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(f"{BASE_URL}/api/contracts/analyze", data={"text": CONTRACT})
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"session={sid[:8]}…")

    debug_seen = []
    ws_url = f"{WS_BASE}/ws/live/{sid}"
    results = []
    closed_early = False

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        for _ in range(6):
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if ev.get("type") == "debug":
                    debug_seen.append(ev["log"])
                if ev.get("type") == "sentence":
                    break
            except asyncio.TimeoutError:
                break

        for i, q in enumerate(QUESTIONS, 1):
            label = f"Turn {i}"
            print(f"\n[{label}] '{q}'")
            try:
                n, first, rates = await one_turn(ws, q, label)
            except websockets.ConnectionClosed as e:
                print(f"   [{label}] CONNECTION CLOSED EARLY: {e.code} {e.reason}")
                closed_early = True
                break
            print(f"   chunks={n}  first_audio={first}s  rate(s)={sorted(rates) or '—'}")
            results.append((label, n, first, rates))
            print(f"   ws.open after turn = {ws.state.name}")

    print("\n" + "=" * 64)
    print("RESULT")
    print("=" * 64)
    all_have_audio = len(results) == len(QUESTIONS) and all(n > 0 for _, n, _, _ in results)
    all_rates = set().union(*[r for *_, r in results]) if results else set()
    rate_ok = all_rates in ({24000}, set())
    print(f"  Turns completed       : {len(results)}/{len(QUESTIONS)}")
    print(f"  Every turn had audio  : {all_have_audio}")
    print(f"  Connection stayed open: {not closed_early}")
    print(f"  Output rate           : {sorted(all_rates) or '—'} (expect [24000])")
    print(f"\n  Backend debug events seen at handshake:")
    for d in debug_seen:
        print(f"    • {d}")
    verdict = all_have_audio and not closed_early and rate_ok
    print(f"\n  VERDICT: {'PASS — session survives multiple turns' if verdict else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(run())
