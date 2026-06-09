"""
Live verification of the final pre-Phase-9 bugfixes over /ws/voice/.
  #1/#2  every risk has a non-empty why_it_matters after analysis
  #3     "write a whatsapp message ... make it short" -> whatsapp draft
  #4     "explain the low risk" -> discusses Low (never "no low-risk items")
  #5     "explain clause N" -> explains risk_00N
Requires backend on :8001 + GEMINI_API_KEY + Journey TTS creds.
"""
import asyncio
import json
import time

import httpx
import websockets

BASE = "http://localhost:8001"
WS = "ws://localhost:8001"

CONTRACT = """\
RESIDENTIAL TENANCY AGREEMENT
1. REPAIRS: Tenant is responsible for ALL repairs, including air-conditioner maintenance and costs beyond normal wear and tear.
2. DEPOSIT: A deposit of $3,000 is held. No interest is paid and refund conditions are at the landlord's sole discretion.
3. EARLY TERMINATION: Tenant pays a penalty of 3 months rent if leaving before the term ends.
4. RENT INCREASE: Landlord may increase rent by any amount at renewal with 7 days notice.
5. QUIET HOURS: No loud noise is permitted after 10pm on weekdays.
6. GUESTS: Overnight guests are limited to a maximum of 14 days per year.
7. PARKING: One parking space is provided; additional vehicles are not permitted.
"""


async def turn(ws, text, settle=22):
    await ws.send(json.dumps({"type": "text_input", "text": text}))
    res = {"sentences": [], "audio": 0, "draft": None, "debug": [], "error": None, "done": None}
    t0 = time.monotonic()
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=settle)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            break
        ev = json.loads(raw); t = ev.get("type")
        if t == "sentence": res["sentences"].append(ev["text"])
        elif t == "audio_chunk": res["audio"] += 1
        elif t == "debug": res["debug"].append(ev["log"])
        elif t == "draft_ready": res["draft"] = ev.get("draft", "")
        elif t == "error": res["error"] = ev.get("message")
        elif t == "audio_done":
            res["done"] = ev.get("turn_id"); break
    res["said"] = " ".join(res["sentences"])
    res["t"] = round(time.monotonic() - t0, 2)
    return res


async def run():
    print("=" * 64)
    async with httpx.AsyncClient(timeout=180) as http:
        r = await http.post(f"{BASE}/api/contracts/analyze", data={"text": CONTRACT})
    r.raise_for_status()
    data = r.json(); sid = data["session_id"]; risks = data["risk_report"]["risks"]
    print(f"session={sid[:8]}  {len(risks)} risks")

    blanks = []
    for x in risks:
        for f in ("title", "severity", "category", "clause_text",
                  "simple_explanation", "why_it_matters", "question_to_ask", "suggested_action"):
            if not str(x.get(f, "")).strip():
                blanks.append((x.get("id"), f))
    sev = {}
    for x in risks:
        sev[x["severity"]] = sev.get(x["severity"], 0) + 1
        print(f"   {x['id']} [{x['severity']:6}] {x['title'][:40]:42} why='{x['why_it_matters'][:38]}'")
    print(f"\n#1/#2 why_it_matters + all fields non-empty: {'PASS' if not blanks else 'FAIL ' + str(blanks)}")
    print(f"      severity breakdown: {sev}")

    lows = [x for x in risks if x["severity"] == "Low"]

    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"{BASE}/api/session/active-clause",
                        json={"session_id": sid, "active_clause_id": risks[0]["id"]})

    async with websockets.connect(f"{WS}/ws/voice/{sid}", max_size=20*1024*1024) as ws:
        tg = time.monotonic()
        while time.monotonic() - tg < 12:
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            except asyncio.TimeoutError:
                break
            if ev.get("type") == "audio_done":
                break

        r3 = await turn(ws, "Write a WhatsApp message about this, make it short.")
        wa = any("format=whatsapp" in d for d in r3["debug"])
        short = any("Make it short" in d for d in r3["debug"])
        print(f"\n#3 whatsapp+short draft: {'PASS' if (wa and short and r3['draft']) else 'FAIL'} "
              f"(whatsapp={wa} short={short} draft={len(r3['draft'] or '')} chars, {r3['t']}s)")
        if r3["draft"]:
            print(f"   draft head: {r3['draft'][:80]!r}")

        r4 = await turn(ws, "Explain the low risk.")
        said4 = r4["said"].lower()
        print(f"\n#4 low risk query: {'PASS' if 'no low-risk' not in said4 and ('low-risk' in said4 or 'low risk' in said4) else 'REVIEW'} "
              f"({r4['t']}s)")
        print(f"   said: {r4['said'][:160]}")
        print(f"   debug: {[d for d in r4['debug'] if 'FastPath' in d or 'severity' in d]}")

        n = int(risks[min(2, len(risks)-1)]["id"].split("_")[1])
        r5 = await turn(ws, f"Explain clause {n}.")
        target_title = risks[min(2, len(risks)-1)]["title"]
        hit = target_title.split()[0].lower() in r5["said"].lower()
        print(f"\n#5 'explain clause {n}' -> risk_{n:03d}: {'PASS' if hit else 'REVIEW'} ({r5['t']}s)")
        print(f"   said: {r5['said'][:160]}")
        print(f"   debug: {[d for d in r5['debug'] if 'FastPath' in d]}")

        dones = [r3["done"], r4["done"], r5["done"]]
        print(f"\n#7 audio_done turn_ids present (no stall): {'PASS' if all(d is not None for d in dones) else 'FAIL'} -> {dones}")
        errs = [r3["error"], r4["error"], r5["error"]]
        print(f"   no error events: {'PASS' if not any(errs) else 'FAIL ' + str(errs)}")

    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(run())
