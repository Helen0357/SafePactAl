"""
Phase 8B - Programmatic E2E test.
Tests the full pipeline: REST upload -> WebSocket voice -> Gemini TTS audio chunks.
Run with: python e2e_voice_test.py
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

This lease is between LANDLORD and TENANT for the property at 123 Main Street.

1. TERM: The lease begins January 1, 2025 and ends December 31, 2025.

2. RENT: Monthly rent is $2,500 due on the 1st. A late fee of 10% per day applies
   to any payment received after the 5th.

3. SECURITY DEPOSIT: Tenant shall pay $5,000. Landlord may deduct any amounts at
   sole discretion with no itemisation required.

4. AUTOMATIC RENEWAL: This lease automatically renews for one year unless either
   party gives 90 days written notice before expiry.

5. ENTRY: Landlord may enter the property at any time without prior notice for any
   reason whatsoever.

6. REPAIRS: Tenant is responsible for all repairs under $500. Landlord is not
   liable for any consequential damages.

7. TERMINATION: Landlord may terminate this lease immediately with 24-hour notice
   for any breach, at sole discretion.
"""

AUDIO_TIMEOUT = 120 


def sec(t):
    return f"{t:.2f}s"


def validate_wav(b64_audio):
    """Decode base64, validate WAV header, return stats dict."""
    try:
        raw = base64.b64decode(b64_audio)
        buf = io.BytesIO(raw)
        with wave.open(buf, "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
        return {
            "valid": True,
            "bytes": len(raw),
            "duration_sec": round(duration, 2),
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc), "bytes": 0}


async def consume_handshake(ws):
    """Read WS messages until we get the greeting sentence."""
    for _ in range(10):
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        ev = json.loads(raw)
        if ev.get("type") == "sentence":
            return ev["text"]
    return ""


async def collect_turn(ws, label, expected_turn_id=1, timeout=AUDIO_TIMEOUT):
    """
    Collect WS events for one turn until audio_done or timeout.
    expected_turn_id: only count audio_chunks whose turn_id matches (ignores
    delayed greeting chunks from previous turns).
    """
    result = {
        "sentences": [],
        "audio_chunks": [],       
        "other_turn_chunks": [],   
        "tts_errors": [],
        "draft_ready": False,
        "draft_text": "",
        "audio_done": False,
        "t_first_sentence": None,
        "t_first_audio": None,
        "t_audio_done": None,
        "seq_order": [],          
    }
    t_start = time.monotonic()
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"    [{label}] TIMEOUT after {sec(time.monotonic()-t_start)}")
            break
        ev = json.loads(raw)
        etype = ev.get("type", "")
        elapsed = time.monotonic() - t_start

        if etype == "sentence":
            if result["t_first_sentence"] is None:
                result["t_first_sentence"] = round(elapsed, 2)
                print(f"    [{label}] First sentence at {sec(elapsed)}: '{ev['text'][:70]}...'")
            result["sentences"].append(ev["text"])

        elif etype == "audio_chunk":
            stats = validate_wav(ev["audio"])
            seq = ev.get("seq", -1)
            turn_id = ev.get("turn_id", -1)
            chunk_info = {
                "seq": seq, "turn_id": turn_id,
                "bytes": stats["bytes"],
                "duration_sec": stats.get("duration_sec"),
                "valid": stats["valid"],
            }
            if turn_id == expected_turn_id:
                result["seq_order"].append(seq)
                result["audio_chunks"].append(chunk_info)
                if result["t_first_audio"] is None:
                    result["t_first_audio"] = round(elapsed, 2)
                    print(f"    [{label}] First audio_chunk at {sec(elapsed)}: "
                          f"seq={seq} turn={turn_id} | {stats['bytes']:,} bytes | "
                          f"{stats.get('duration_sec', '?')}s audio | valid={stats['valid']}")
            else:
                result["other_turn_chunks"].append(chunk_info)
                print(f"    [{label}] Delayed chunk discarded: seq={seq} turn={turn_id} "
                      f"(expected turn={expected_turn_id})")

        elif etype == "tts_error":
            print(f"    [{label}] TTS ERROR seq={ev.get('seq')}: {ev.get('message')}")
            result["tts_errors"].append(ev)

        elif etype == "draft_ready":
            result["draft_ready"] = True
            result["draft_text"] = ev.get("draft", "")
            print(f"    [{label}] draft_ready: {len(result['draft_text'])} chars")
            print(f"    Preview: '{result['draft_text'][:80]}...'")

        elif etype == "audio_done":
            result["t_audio_done"] = round(elapsed, 2)
            result["audio_done"] = True
            print(f"    [{label}] audio_done at {sec(elapsed)}")
            break

        elif etype == "status":
            state = ev.get("state", "")
            if state == "idle" and result["audio_done"]:
                break

    return result


async def run_e2e():
    print("\n" + "=" * 60)
    print("Phase 8B  Programmatic E2E Test")
    print("=" * 60)

    # ── 1. Upload contract ─────────────────────────────────────────
    print("\n[1] Uploading sample contract...")
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=120) as http:
        resp = await http.post(
            f"{BASE_URL}/api/contracts/analyze",
            data={"text": SAMPLE_CONTRACT},
        )
    upload_s = time.monotonic() - t0
    if resp.status_code != 200:
        print(f"    FAIL HTTP {resp.status_code}: {resp.text[:200]}")
        return
    data = resp.json()
    session_id = data["session_id"]
    risks = data["risk_report"]["risks"]
    risk_count = len(risks)
    first_risk_id = risks[0]["id"] if risks else None
    print(f"    PASS: session={session_id[:8]}... | {risk_count} risks | {sec(upload_s)}")

    ws_url = f"{WS_BASE}/ws/voice/{session_id}"

    # ── 2. Q1: biggest risk ────────────────────────────────────────
    print(f"\n[2] Q1 - 'What is the biggest risk?'")
    t_ws = time.monotonic()
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        ws_ms = (time.monotonic() - t_ws) * 1000
        print(f"    WS connected in {ws_ms:.0f}ms")
        greeting = await consume_handshake(ws)
        print(f"    Greeting: '{greeting[:70]}...'")

        t_send = time.monotonic()
        await ws.send(json.dumps({
            "type": "text_input",
            "text": "What is the biggest risk in this contract?",
        }))
        q1 = await collect_turn(ws, "Q1")

    # ── 3. Set active clause + Q2: explain ────────────────────────
    print(f"\n[3] Set active clause + Q2 - 'Explain this clause'")
    if first_risk_id:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                f"{BASE_URL}/api/session/active-clause",
                json={"session_id": session_id, "active_clause_id": first_risk_id},
            )
        print(f"    Set active clause HTTP {r.status_code}: {first_risk_id}")

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        await consume_handshake(ws)
        await ws.send(json.dumps({
            "type": "text_input",
            "text": "Explain this clause in simple terms.",
        }))
        q2 = await collect_turn(ws, "Q2", expected_turn_id=1)  # new WS session — turn resets to 1

    # ── 4. Q3: draft_ready ────────────────────────────────────────
    print(f"\n[4] Q3 - 'Write a professional email about the late fee clause'")
    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        await consume_handshake(ws)
        await ws.send(json.dumps({
            "type": "text_input",
            "text": "Write me a professional email about the late fee clause.",
        }))
        q3 = await collect_turn(ws, "Q3", expected_turn_id=1, timeout=AUDIO_TIMEOUT)  # new WS session

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    for label, r in [("Q1 biggest risk", q1), ("Q2 explain clause", q2), ("Q3 draft email", q3)]:
        chunks = r["audio_chunks"]
        seqs = r["seq_order"]
        print(f"\n{label}:")
        print(f"  Sentences:          {len(r['sentences'])}")
        print(f"  Audio chunks:       {len(chunks)}")
        if chunks:
            total_bytes = sum(c["bytes"] for c in chunks)
            total_dur   = sum(c.get("duration_sec") or 0 for c in chunks)
            all_valid   = all(c["valid"] for c in chunks)
            in_order    = seqs == sorted(seqs)
            print(f"  Total WAV audio:    {total_bytes:,} bytes / {total_dur:.1f}s")
            print(f"  All WAV valid:      {all_valid}")
            print(f"  Chunks in order:    {in_order}  (seqs={seqs})")
        print(f"  TTS errors:         {len(r['tts_errors'])}")
        print(f"  t_first_sentence:   {r['t_first_sentence']}s")
        print(f"  t_first_audio:      {r['t_first_audio']}s")
        print(f"  t_audio_done:       {r['t_audio_done']}s")
        print(f"  draft_ready:        {r['draft_ready']}")
        if r["draft_ready"] and r["draft_text"]:
            print(f"  Draft preview:      '{r['draft_text'][:80]}...'")
        ok = len(r["sentences"]) > 0 or r["draft_ready"]
        print(f"  Status:             {'PASS' if ok else 'FAIL'}")

    audio_ok = any(len(r["audio_chunks"]) > 0 for r in [q1, q2, q3])
    print(f"\nAudio chunks received:  {'YES' if audio_ok else 'NO - TTS pipeline issue'}")
    print(f"draft_ready working:    {q3['draft_ready']}")
    all_ok = (
        len(q1["sentences"]) > 0 and len(q1["audio_chunks"]) > 0 and
        len(q2["sentences"]) > 0 and len(q2["audio_chunks"]) > 0 and
        q3["draft_ready"]
    )
    print(f"Overall E2E:            {'ALL PASS' if all_ok else 'PARTIAL - see above'}")


if __name__ == "__main__":
    asyncio.run(run_e2e())
