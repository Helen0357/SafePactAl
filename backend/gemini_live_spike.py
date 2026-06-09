"""
Phase 8D — Gemini Live native audio spike test.

Tests the full pipeline:
  text input → Gemini Live session → PCM audio → WAV file + timing

No FastAPI, no server. Run standalone:
  cd backend
  python gemini_live_spike.py

Produces:
  - Console timing report (time to first audio, total audio duration)
  - spike_out_q1.wav / spike_out_q2.wav / spike_out_q3.wav  (listen to assess quality)
  - Comparison: Journey TTS vs Gemini Live
"""
import asyncio
import base64
import io
import os
import sys
import time
import wave
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

_AGENT_ROOT = Path(__file__).parent.parent / "agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

# ── Config ─────────────────────────────────────────────────────────────────────
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
# Ordered by likelihood of working with an AI Studio key.
# Phase 5 confirmed gemini-2.5-flash-native-audio-latest connects via bidiGenerateContent.
# gemini-2.0-flash-live-001 requires v1 API (not available in AI Studio v1beta).
LIVE_MODEL_CANDIDATES = [
    "gemini-2.5-flash-native-audio-latest",        
    "gemini-live-2.5-flash-preview",              
    "gemini-2.5-flash-preview-native-audio-dialog",
    os.environ.get("GEMINI_LIVE_MODEL", ""),      
]
VOICE_NAME      = "Charon"   

# ── Sample contract context ────────────────────────────────────────────────────
SAMPLE_SYSTEM = """\
You are ProtectMe AI, a contract-risk assistant in a live voice call.
Contract: Residential Lease | Risk: High | Advice: Do Not Sign Yet

Key risks:
• Late Fee 10%/day: 10 percent daily late fee compounds extremely fast.
• Unlimited Entry: Landlord may enter at any time without notice.
• Automatic Renewal: Lease auto-renews unless 90 days written notice given.

Rules: MAX 2 short sentences. Key finding first. Warm, direct tone. Not legal advice."""

TEST_QUESTIONS = [
    ("Q1", "What is the biggest risk in this contract?"),
    ("Q2", "Should I sign this lease?"),
    ("Q3", "Explain the late fee clause simply."),
]

# ── Audio helpers ──────────────────────────────────────────────────────────────
_SAMPLE_RATE  = 24_000
_CHANNELS     = 1
_SAMPLE_WIDTH = 2   

_PCM_BUFFER_MS = 300  
_PCM_BUFFER_BYTES = _SAMPLE_RATE * _SAMPLE_WIDTH * _CHANNELS * _PCM_BUFFER_MS // 1000


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def _wav_duration_ms(wav: bytes) -> int:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)


def _extract_pcm(response) -> Optional[bytes]:
    """Extract raw PCM bytes from a Gemini Live response (handles SDK variations)."""
    d = getattr(response, "data", None)
    if d and isinstance(d, bytes):
        return d

    sc = getattr(response, "server_content", None)
    if sc:
        mt = getattr(sc, "model_turn", None)
        if mt:
            for part in getattr(mt, "parts", []) or []:
                raw = getattr(getattr(part, "inline_data", None), "data", None)
                if raw:
                    return base64.b64decode(raw) if isinstance(raw, str) else raw
    return None


def _is_turn_complete(response) -> bool:
    sc = getattr(response, "server_content", None)
    return bool(sc and getattr(sc, "turn_complete", False))


def _is_interrupted(response) -> bool:
    sc = getattr(response, "server_content", None)
    return bool(sc and getattr(sc, "interrupted", False))


# ── Core spike logic ───────────────────────────────────────────────────────────

async def run_live_turn(session, question: str) -> dict:
    """
    Send one question to the Gemini Live session.
    Returns timing and audio stats.
    """
    t_start = time.monotonic()
    t_first_audio: Optional[float] = None
    all_pcm = b""
    chunk_count = 0

    from google.genai import types as _t
    await session.send_client_content(
        turns=[_t.Content(parts=[_t.Part(text=question)], role="user")],
        turn_complete=True,
    )

    async for response in session.receive():
        pcm = _extract_pcm(response)
        if pcm:
            all_pcm += pcm
            if t_first_audio is None:
                t_first_audio = time.monotonic() - t_start
            chunk_count += 1

        if _is_turn_complete(response) or _is_interrupted(response):
            break

    t_total = time.monotonic() - t_start

    return {
        "t_first_audio_s": round(t_first_audio or 0, 2),
        "t_total_s": round(t_total, 2),
        "pcm_bytes": len(all_pcm),
        "audio_chunks_received": chunk_count,
        "all_pcm": all_pcm,
    }


async def run_spike():
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set in backend/.env")
        return

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("ERROR: google-genai SDK not installed. Run: pip install google-genai")
        return

    client = genai.Client(api_key=GEMINI_API_KEY)

    print("\n" + "=" * 60)
    print("Phase 8D — Gemini Live Native Audio Spike")
    print(f"Voice : {VOICE_NAME}")
    print("=" * 60)

    # ── Connection config ──────────────────────────────────────
    try:
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=SAMPLE_SYSTEM)],
                role="user",
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=VOICE_NAME,
                    )
                )
            ),
        )
    except Exception as e:
        print(f"ERROR building config: {e}")
        return

    # ── Discover which model is available ──────────────────────
    live_model = None
    for candidate in LIVE_MODEL_CANDIDATES:
        if not candidate:
            continue
        print(f"\nTrying model: {candidate} ...")
        try:
            async with client.aio.live.connect(model=candidate, config=live_config) as _test:
                live_model = candidate
                print(f"  OK — connected.\n")
                break
        except Exception as exc:
            print(f"  FAIL: {str(exc)[:120]}")

    if not live_model:
        print("\nNo Gemini Live model available with this API key.")
        print("This key may require Vertex AI for Live access, or the models are in limited preview.")
        print("RECOMMENDATION: Keep Google Cloud Journey TTS (Phase 8C) as primary.")
        return

    results = []
    print(f"Using model: {live_model}\n")

    try:
        t_connect = time.monotonic()
        async with client.aio.live.connect(model=live_model, config=live_config) as session:
            connect_ms = int((time.monotonic() - t_connect) * 1000)
            print(f"Connected in {connect_ms}ms\n")

            for label, question in TEST_QUESTIONS:
                print(f"[{label}] '{question}'")
                try:
                    stats = await run_live_turn(session, question)
                    stats["label"] = label
                    stats["question"] = question
                    results.append(stats)

                    if stats["all_pcm"]:
                        wav = _pcm_to_wav(stats["all_pcm"])
                        audio_dur = _wav_duration_ms(wav)
                        fname = f"spike_out_{label.lower()}.wav"
                        Path(fname).write_bytes(wav)
                        print(f"  t_first_audio : {stats['t_first_audio_s']}s")
                        print(f"  t_total       : {stats['t_total_s']}s")
                        print(f"  audio         : {len(stats['all_pcm']):,} PCM bytes / {audio_dur}ms")
                        print(f"  saved to      : {fname}")
                    else:
                        print(f"  WARNING: No audio received!")
                        print(f"  t_total: {stats['t_total_s']}s, chunks: {stats['audio_chunks_received']}")
                    print()

                except Exception as exc:
                    print(f"  ERROR: {exc}\n")
                    results.append({"label": label, "error": str(exc)})

    except Exception as exc:
        print(f"LIVE CONNECTION FAILED: {exc}")
        print("\nFallback recommendation: Use Google Cloud Journey TTS (Phase 8C)")
        return

    # ── Summary ────────────────────────────────────────────────
    print("=" * 60)
    print("SPIKE SUMMARY")
    print("=" * 60)
    ok_results = [r for r in results if "error" not in r and r.get("t_first_audio_s")]
    if ok_results:
        avg_first = sum(r["t_first_audio_s"] for r in ok_results) / len(ok_results)
        avg_total = sum(r["t_total_s"] for r in ok_results) / len(ok_results)
        print(f"Questions answered  : {len(ok_results)}/{len(TEST_QUESTIONS)}")
        print(f"Avg time to first audio : {avg_first:.2f}s")
        print(f"Avg total response time : {avg_total:.2f}s")
        print()

        print("Latency assessment vs threshold:")
        print(f"  < 1.5s first audio : {'PASS' if avg_first < 1.5 else 'FAIL'}")
        print(f"  < 3.0s first audio : {'PASS' if avg_first < 3.0 else 'FAIL'}")
        print(f"  < 5.0s first audio : {'PASS' if avg_first < 5.0 else 'FAIL'}")
        print()
        print("Journey TTS pipeline for comparison:")
        print("  t_first_sentence  : ~4-6s (Gemini inference)")
        print("  Journey TTS latency: ~300ms")
        print("  t_first_audio     : ~4.3-6.3s")
        print()

        if avg_first < 3.0:
            print("VERDICT: Gemini Live is significantly faster than Journey TTS.")
            print("RECOMMENDATION: Use Gemini Live as primary for Call Your Agent.")
        elif avg_first < 6.0:
            print("VERDICT: Gemini Live is comparable to Journey TTS.")
            print("RECOMMENDATION: Use Gemini Live for its voice quality; latency is similar.")
        else:
            print("VERDICT: Gemini Live is slower than Journey TTS in current conditions.")
            print("RECOMMENDATION: Keep Journey TTS; investigate Gemini Live again later.")
    else:
        print("All questions failed. Gemini Live not available with current credentials.")
        print("RECOMMENDATION: Keep Journey TTS (Phase 8C) as primary.")

    print("\nAudio samples saved as spike_out_q*.wav — listen to assess voice quality.")
    print("Delete them when done (they are not committed to git).")


if __name__ == "__main__":
    asyncio.run(run_spike())
