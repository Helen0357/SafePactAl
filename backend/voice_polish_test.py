"""
Phase 8F-mod-2 — final voice polish verification over /ws/voice/.

Covers the new English behaviors:
  • detail-mode explain (richer, <=5 sentences, uses the active clause)
  • modify_message  (generate a draft, then "make it shorter" → new draft_ready)
  • recommendation  (careful, contextual, no legal certainty)
  • audio_done carries the real turn_id

Requires backend on :8001 + GEMINI_API_KEY + Journey TTS creds.
"""
import asyncio
import io
import json
import time
import wave
import base64

import httpx
import websockets

BASE_URL = "http://localhost:8001"
WS_BASE  = "ws://localhost:8001"

CONTRACT = """\
RESIDENTIAL TENANCY AGREEMENT
1. REPAIRS: Tenant is responsible for ALL repairs, including beyond normal wear and tear.
2. DEPOSIT: $3,000 held. No interest is paid on the deposit.
3. EARLY TERMINATION: Tenant pays a penalty of 3 months rent if leaving before the term ends.
"""


def count_sentences(parts):
    return len([p for p in parts if p.strip()])


async def turn(ws, text, label, settle=18):
    await ws.send(json.dumps({"type": "text_input", "text": text}))
    res = {"sentences": [], "audio": 0, "draft": None, "debug": [], "error": None,
           "audio_done_turn": None, "first_audio": None}
    t0 = time.monotonic()
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=settle)
        except asyncio.TimeoutError:
            break
        except websockets.ConnectionClosed as e:
            res["error"] = f"closed {e.code}"; break
        ev = json.loads(raw); t = ev.get("type")
        if t == "sentence":
            res["sentences"].append(ev["text"])
        elif t == "audio_chunk":
            res["audio"] += 1
            if res["first_audio"] is None:
                res["first_audio"] = round(time.monotonic() - t0, 2)
        elif t == "debug":
            res["debug"].append(ev["log"])
        elif t == "draft_ready":
            res["draft"] = ev.get("draft", "")
        elif t == "error":
            res["error"] = ev.get("message")
        elif t == "audio_done":
            res["audio_done_turn"] = ev.get("turn_id")
            break
    return res


def show(label, r):
    fp = [d for d in r["debug"] if any(k in d for k in ("FastPath", "Modify", "Recommendation", "VoiceFallback", "active clause"))]
    print(f"\n[{label}]  audio={r['audio']} first={r['first_audio']}s sentences={count_sentences(r['sentences'])} audio_done_turn={r['audio_done_turn']}")
    for d in fp:
        print(f"   · {d}")
    print(f"   said: {' '.join(r['sentences'])[:200]}")
    if r["draft"] is not None:
        print(f"   draft_ready: {len(r['draft'])} chars")
    if r["error"]:
        print(f"   ERROR: {r['error']}")


async def run():
    print("=" * 64)
    print("Phase 8F-mod-2 — voice polish (/ws/voice/)")
    print("=" * 64)
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(f"{BASE_URL}/api/contracts/analyze", data={"text": CONTRACT})
    r.raise_for_status()
    data = r.json(); sid = data["session_id"]; risks = data["risk_report"]["risks"]
    target = next((x for x in risks if "deposit" in x["title"].lower()), risks[0])
    print(f"session={sid[:8]}  {len(risks)} risks  | target clause {target['id']} = {target['title']}")

    async with httpx.AsyncClient(timeout=30) as http:
        await http.post(f"{BASE_URL}/api/session/active-clause",
                        json={"session_id": sid, "active_clause_id": target["id"]})

    ws_url = f"{WS_BASE}/ws/voice/{sid}"
    R = {}
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        tg = time.monotonic()
        while time.monotonic() - tg < 12:
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=12))
            except asyncio.TimeoutError:
                break
            if ev.get("type") == "audio_done":
                break

        R["detail"] = await turn(ws, "Can you explain this point in a more easy way?", "detail")
        R["gen"]    = await turn(ws, "Write me a professional email about this.", "generate", settle=22)
        R["modify"] = await turn(ws, "This one is not enough yet, please make it shorter.", "modify", settle=22)
        R["rec1"]   = await turn(ws, "I did not sign yet and I did not pay money yet. Can he charge me?", "rec1")
        R["rec2"]   = await turn(ws, "If he refuses to negotiate, should I reject?", "rec2")

    for k, v in R.items():
        show(k, v)

    print("\n" + "=" * 64)
    print("VERDICT")
    print("=" * 64)
    detail_used = any("detail_explain using " + target["id"] in d for d in R["detail"]["debug"])
    detail_len = count_sentences(R["detail"]["sentences"])
    detail_ok = detail_used and 1 < detail_len <= 5
    gen_ok = bool(R["gen"]["draft"])
    modify_used = any("ModifyMessage" in d for d in R["modify"]["debug"])
    modify_ok = modify_used and bool(R["modify"]["draft"])
    shorter_ok = modify_ok and len(R["modify"]["draft"]) < len(R["gen"]["draft"] or "")
    said_modify = " ".join(R["modify"]["sentences"]).lower()
    voice_confirms = "short" in said_modify or "updated" in said_modify
    rec1 = " ".join(R["rec1"]["sentences"]).lower()
    rec_careful = any(p in rec1 for p in ["confirm in writing", "in writing", "based on", "usually", "haven't signed", "have not signed", "not bind"])
    rec_no_certainty = not any(p in rec1 for p in ["you will not be charged", "definitely", "guarantee", "100%", "legally cannot"])
    audio_done_ok = all(R[k]["audio_done_turn"] not in (None, "?") for k in R)
    no_errors = all(R[k]["error"] is None for k in R)

    print(f"  Detail uses active clause + <=5 sentences : {detail_ok} (sentences={detail_len})")
    print(f"  Email generated (draft_ready)             : {gen_ok}")
    print(f"  'make it shorter' -> modify_message       : {modify_ok}")
    print(f"  Modified draft is shorter                 : {shorter_ok} ({len(R['gen']['draft'] or '')} -> {len(R['modify']['draft'] or '')} chars)")
    print(f"  Voice confirms the change                 : {voice_confirms}")
    print(f"  Recommendation careful + contextual       : {rec_careful}")
    print(f"  Recommendation avoids legal certainty     : {rec_no_certainty}")
    print(f"  audio_done carries real turn_id           : {audio_done_ok}")
    print(f"  No error events                           : {no_errors}")
    ok = detail_ok and gen_ok and modify_ok and voice_confirms and rec_careful and rec_no_certainty and audio_done_ok and no_errors
    print(f"\n  RESULT: {'PASS' if ok else 'REVIEW - see above'}")


if __name__ == "__main__":
    asyncio.run(run())
