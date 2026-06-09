"""
Phase 8F — Journey TTS demo-flow test against the production /ws/voice/ route.

Mirrors the PM's required browser test, but driven over the WebSocket so the
backend half is verified deterministically:

  upload → /ws/voice/ → biggest risk → (set active clause) → explain this clause
  → should I sign → write a message → 2 follow-ups

Asserts:
  • every turn streams audio_chunk(s)  (voice works ≥5 turns)
  • fast paths fire from the report (no Gemini) for the common questions
  • "explain this clause" answers about the SELECTED clause
  • draft_ready appears for the message request
  • no error events; connection stays open the whole time

Requires backend on :8001 + GEMINI_API_KEY + Journey TTS creds.
Run:  python voice_demo_flow_test.py
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
RESIDENTIAL TENANCY AGREEMENT
1. REPAIRS: Tenant is responsible for ALL repairs to the premises, fixtures and
   fittings, including those beyond normal wear and tear.
2. DEPOSIT: A deposit of $3,000 is held. No interest is paid on the deposit.
3. ENTRY: Landlord may enter at any time without notice.
4. RENEWAL: Agreement auto-renews for 12 months unless 90 days notice is given.
"""


def wav_rate(b64: str) -> int:
    with wave.open(io.BytesIO(base64.b64decode(b64)), "rb") as wf:
        return wf.getframerate()


async def turn(ws, text, label, settle=12):
    """Send one user turn; collect until audio_done. Returns a summary dict."""
    await ws.send(json.dumps({"type": "text_input", "text": text}))
    res = {"sentences": [], "audio": 0, "draft": None, "debug": [],
           "error": None, "first_audio": None, "rates": set()}
    t0 = time.monotonic()
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=settle)
        except asyncio.TimeoutError:
            break
        except websockets.ConnectionClosed as e:
            res["error"] = f"closed {e.code}"
            break
        ev = json.loads(raw)
        t = ev.get("type")
        if t == "sentence":
            res["sentences"].append(ev["text"])
        elif t == "audio_chunk":
            res["audio"] += 1
            res["rates"].add(wav_rate(ev["audio"]))
            if res["first_audio"] is None:
                res["first_audio"] = round(time.monotonic() - t0, 2)
        elif t == "debug":
            res["debug"].append(ev["log"])
        elif t == "draft_ready":
            res["draft"] = ev.get("draft", "")
        elif t == "error":
            res["error"] = ev.get("message")
        elif t == "audio_done":
            break
    return res


def show(label, r):
    fp = [d for d in r["debug"] if "FastPath" in d or "answering about active" in d]
    print(f"\n[{label}]")
    print(f"   audio_chunks={r['audio']}  first_audio={r['first_audio']}s  rates={sorted(r['rates']) or '—'}")
    if fp:
        for d in fp:
            print(f"   {d}")
    print(f"   said: {' '.join(r['sentences'])[:170]}")
    if r["draft"] is not None:
        print(f"   draft_ready: {len(r['draft'])} chars")
    if r["error"]:
        print(f"   ERROR: {r['error']}")


async def run():
    print("=" * 64)
    print("Phase 8F — Journey TTS demo flow (/ws/voice/)")
    print("=" * 64)

    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(f"{BASE_URL}/api/contracts/analyze", data={"text": CONTRACT})
    r.raise_for_status()
    data = r.json()
    sid = data["session_id"]
    risks = data["risk_report"]["risks"]
    print(f"session={sid[:8]}…  {len(risks)} risks")
    target = next((x for x in risks if "deposit" in x["title"].lower()), risks[-1])
    print(f"target clause for 'explain': {target['id']} — {target['title']}")

    ws_url = f"{WS_BASE}/ws/voice/{sid}"
    results = {}
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        gt = await turn_drain_greeting(ws)
        print(f"\n[greeting] audio_chunks={gt}")

        results["Q1 largest risk"] = await turn(ws, "What is the largest risk?", "Q1")
        results["Q1b largest scale"] = await turn(ws, "What is the largest scale?", "Q1b")

        async with httpx.AsyncClient(timeout=30) as http:
            ar = await http.post(f"{BASE_URL}/api/session/active-clause",
                                 json={"session_id": sid, "active_clause_id": target["id"]})
        print(f"\n[set active clause] HTTP {ar.status_code} -> {target['id']}")

        results["Q2 explain clause"] = await turn(ws, "Explain this clause.", "Q2")
        results["Q3 should I sign"] = await turn(ws, "Should I sign?", "Q3")
        results["Q4 write message"] = await turn(ws, "Write me a professional message about this.", "Q4", settle=20)
        results["Q5 complex"] = await turn(ws, "What happens if I break the lease early?", "Q5", settle=20)
        results["Q6 follow-up"] = await turn(ws, "What questions should I ask before signing?", "Q6")

    for label, res in results.items():
        show(label, res)

    print("\n" + "=" * 64)
    print("VERDICT")
    print("=" * 64)
    turns = list(results.values())
    voice_every_turn = all(t["audio"] > 0 for t in turns)
    no_errors = all(t["error"] is None for t in turns)
    q1_fast = any("biggest_risk" in d for d in results["Q1 largest risk"]["debug"])
    q1b_fast = any("biggest_risk" in d for d in results["Q1b largest scale"]["debug"])
    q2_active = any("explain_active_clause using " + target["id"] in d for d in results["Q2 explain clause"]["debug"])
    q2_about_target = "deposit" in " ".join(results["Q2 explain clause"]["sentences"]).lower()
    q3_fast = any("should_i_sign" in d for d in results["Q3 should I sign"]["debug"])
    draft_ok = bool(results["Q4 write message"]["draft"])
    q5_text = " ".join(results["Q5 complex"]["sentences"]).lower()
    bad_phrases = ["share the", "provide the list", "list of the", "share your", "give me the list",
                   "don't have the", "do not have", "please share", "as an ai"]
    q5_no_ask_for_list = not any(p in q5_text for p in bad_phrases)
    q1_first_audio = results["Q1 largest risk"]["first_audio"]
    print(f"  Voice on every turn (>=5)    : {voice_every_turn}")
    print(f"  No error events              : {no_errors}")
    print(f"  Q1 'largest risk' fast-path  : {q1_fast}  (first_audio={q1_first_audio}s)")
    print(f"  Q1b 'largest scale' fast-path: {q1b_fast}")
    print(f"  Q2 used active clause        : {q2_active}")
    print(f"  Q2 answer about that clause  : {q2_about_target}")
    print(f"  Q3 fast-path should_i_sign   : {q3_fast}")
    print(f"  Q4 draft_ready               : {draft_ok}")
    print(f"  Q5 fallback never asks list  : {q5_no_ask_for_list}")
    ok = voice_every_turn and no_errors and q1_fast and q1b_fast and q2_active and q2_about_target and q3_fast and draft_ok and q5_no_ask_for_list
    print(f"\n  RESULT: {'PASS' if ok else 'REVIEW - see above'}")


async def turn_drain_greeting(ws, timeout=15):
    audio = 0
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            break
        ev = json.loads(raw)
        if ev.get("type") == "audio_chunk":
            audio += 1
        elif ev.get("type") == "audio_done":
            break
        elif ev.get("type") == "sentence" and audio == 0:
            pass
    return audio


if __name__ == "__main__":
    asyncio.run(run())
