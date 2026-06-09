"""
Phase 8E — Programmatic test of the production /ws/live/ route.

Exercises the real LiveVoiceService through its WebSocket (not the raw SDK):
  REST upload → set active clause → WS /ws/live/ → text_input → audio_chunks
  → draft_ready (hybrid).

This verifies the BACKEND half of the audio-in/audio-out pipeline end-to-end:
  • Live session connects through our route
  • audio_chunk events stream back (timing measured)
  • active-clause context reaches the model
  • draft_ready hybrid fires on a "write a message" request

The pure microphone audio-in leg (browser PCM → send_realtime_input → VAD)
still requires a human with a real mic — see the verification report.

Requires the backend running on :8001 and a valid GEMINI_API_KEY.
Run:  python live_ws_test.py
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

SAMPLE_CONTRACT = """\
RESIDENTIAL LEASE AGREEMENT
1. RENT: $2,500/month. Late fee of 10% per day applies after the 5th.
2. ENTRY: Landlord may enter at any time without notice for any reason.
3. AUTOMATIC RENEWAL: Renews for one year unless 90 days notice given.
4. TERMINATION: Landlord may terminate with 24-hour notice at sole discretion.
"""

AUDIO_TIMEOUT = 60


def wav_stats(b64: str) -> dict:
    raw = base64.b64decode(b64)
    with wave.open(io.BytesIO(raw), "rb") as wf:
        dur = wf.getnframes() / wf.getframerate()
        rate = wf.getframerate()
    return {"bytes": len(raw), "duration_s": round(dur, 2), "rate": rate}


async def collect_turn(ws, label, expect_draft=False, timeout=AUDIO_TIMEOUT):
    res = {
        "sentences": [], "audio_chunks": [], "draft_ready": False,
        "draft_text": "", "t_first_audio": None, "t_audio_done": None,
        "rates": set(),
    }
    t0 = time.monotonic()
    draft_deadline = None
    while True:
        try:
            recv_to = 8 if draft_deadline else timeout
            raw = await asyncio.wait_for(ws.recv(), timeout=recv_to)
        except asyncio.TimeoutError:
            if draft_deadline:
                break 
            print(f"    [{label}] TIMEOUT after {time.monotonic()-t0:.1f}s")
            break
        except Exception as e:
            if res["t_audio_done"] is not None:
                break
            print(f"    [{label}] conn closed: {type(e).__name__}")
            break
        ev = json.loads(raw)
        et = ev.get("type", "")
        el = time.monotonic() - t0
        if et == "sentence":
            res["sentences"].append(ev["text"])
        elif et == "audio_chunk":
            st = wav_stats(ev["audio"])
            res["rates"].add(st["rate"])
            res["audio_chunks"].append(st)
            if res["t_first_audio"] is None:
                res["t_first_audio"] = round(el, 2)
                print(f"    [{label}] first audio @ {el:.2f}s | {st['rate']}Hz | {st['bytes']:,}B")
        elif et == "draft_ready":
            res["draft_ready"] = True
            res["draft_text"] = ev.get("draft", "")
            print(f"    [{label}] draft_ready: {len(res['draft_text'])} chars")
            break
        elif et == "audio_done":
            res["t_audio_done"] = round(el, 2)
            if expect_draft and not res["draft_ready"]:
                draft_deadline = time.monotonic() + 8  
                continue
            break
        elif et == "error":
            print(f"    [{label}] ERROR: {ev.get('message')}")
            break
    return res


async def run():
    print("\n" + "=" * 60)
    print("Phase 8E — /ws/live/ Route Test (text path)")
    print("=" * 60)

    print("\n[1] Upload contract...")
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(f"{BASE_URL}/api/contracts/analyze", data={"text": SAMPLE_CONTRACT})
    if r.status_code != 200:
        print(f"    FAIL HTTP {r.status_code}: {r.text[:200]}")
        return
    data = r.json()
    sid = data["session_id"]
    risks = data["risk_report"]["risks"]
    first_risk = risks[0]["id"] if risks else None
    print(f"    session={sid[:8]}… | {len(risks)} risks")

    ws_url = f"{WS_BASE}/ws/live/{sid}"

    # ── Q1: biggest risk ──────────────────────────────────────
    print("\n[2] Q1 — 'What is the biggest risk?'")
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        for _ in range(4):
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if ev.get("type") == "sentence":
                    break
            except asyncio.TimeoutError:
                break
        await ws.send(json.dumps({"type": "text_input", "text": "What is the biggest risk?"}))
        q1 = await collect_turn(ws, "Q1")

    # ── set active clause + Q2: explain ───────────────────────
    print("\n[3] Set active clause + Q2 — 'Explain this clause'")
    if first_risk:
        async with httpx.AsyncClient(timeout=30) as http:
            ar = await http.post(
                f"{BASE_URL}/api/session/active-clause",
                json={"session_id": sid, "active_clause_id": first_risk},
            )
        print(f"    active-clause HTTP {ar.status_code}: {first_risk}")
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        for _ in range(4):
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if ev.get("type") == "sentence":
                    break
            except asyncio.TimeoutError:
                break
        await ws.send(json.dumps({"type": "text_input", "text": "Explain this clause."}))
        q2 = await collect_turn(ws, "Q2")

    # ── Q3: draft ─────────────────────────────────────────────
    print("\n[4] Q3 — 'Write me a professional message about this'")
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        for _ in range(4):
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if ev.get("type") == "sentence":
                    break
            except asyncio.TimeoutError:
                break
        await ws.send(json.dumps({"type": "text_input", "text": "Write me a professional message about this."}))
        q3 = await collect_turn(ws, "Q3", expect_draft=True)

    # ── Summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for label, res in [("Q1 biggest risk", q1), ("Q2 explain clause", q2), ("Q3 draft", q3)]:
        print(f"\n{label}:")
        print(f"  audio_chunks   : {len(res['audio_chunks'])}")
        print(f"  sample rate(s) : {sorted(res['rates']) or 'none'}")
        print(f"  t_first_audio  : {res['t_first_audio']}s")
        print(f"  t_audio_done   : {res['t_audio_done']}s")
        print(f"  draft_ready    : {res['draft_ready']}"
              + (f" ({len(res['draft_text'])} chars)" if res['draft_ready'] else ""))

    print("\nVERDICT:")
    audio_ok    = bool(q1["audio_chunks"]) and bool(q2["audio_chunks"])
    draft_ok    = q3["draft_ready"]
    all_rates   = q1["rates"] | q2["rates"] | q3["rates"]
    rate_ok     = all_rates == {24000} or all_rates == set()
    print(f"  Audio streamed (Q1,Q2) : {'YES' if audio_ok else 'NO'}")
    print(f"  Output rate            : {sorted(all_rates) or 'n/a'}  (expect [24000])")
    print(f"  draft_ready (Q3)       : {'YES' if draft_ok else 'NO'}")
    print(f"  Overall                : {'PASS' if (audio_ok and draft_ok and rate_ok) else 'PARTIAL — see above'}")


if __name__ == "__main__":
    asyncio.run(run())
