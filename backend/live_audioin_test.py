"""
Audio-IN regression test for the rejected-Live fix.

The browser bug: the very first audio_input chunk killed the Live session
(`media=[Blob]` is wrong — audio must use `audio=Blob`). Symptom in the log:
  [Live] received audio_input chunk #1
  [Live] Gemini Live session closed (audio_input received=1, audio chunks sent=0)
  WS closed code=1006

This test reproduces the REAL mic path without a browser: it synthesizes
spoken audio with Google Cloud TTS (16 kHz LINEAR16), strips it to raw PCM,
streams it as audio_input chunks over /ws/live/, then asserts that:
  • the session does NOT close after chunk #1 (the bug),
  • many audio_input chunks are accepted,
  • Gemini Live responds with audio_chunk(s) via VAD.

Requires backend on :8001, GEMINI_API_KEY, and Google Cloud TTS creds.
Run:  python live_audioin_test.py
"""
import asyncio
import base64
import io
import json
import os
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from app.core.config import settings  
if settings.google_application_credentials:
    cred = (Path(__file__).resolve().parent / settings.google_application_credentials)
    if cred.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred)

BASE_URL = "http://localhost:8001"
WS_BASE  = "ws://localhost:8001"

CONTRACT = """\
RESIDENTIAL LEASE AGREEMENT
1. RENT: $2,500/month. Late fee of 10% per day after the 5th.
2. ENTRY: Landlord may enter at any time without notice.
3. AUTO-RENEWAL: Renews yearly unless 90 days notice given.
"""

UTTERANCE = "What is the biggest risk in this contract?"
CHUNK_MS  = 128  


async def synth_pcm_16k(text: str) -> bytes:
    """Synthesize speech as raw 16 kHz / 16-bit / mono PCM via Google Cloud TTS."""
    from google.cloud import texttospeech as tts
    client = tts.TextToSpeechAsyncClient()
    resp = await client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code="en-US", name="en-US-Journey-F"),
        audio_config=tts.AudioConfig(
            audio_encoding=tts.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
        ),
    )
    with wave.open(io.BytesIO(resp.audio_content), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getsampwidth() == 2 and wf.getnchannels() == 1
        return wf.readframes(wf.getnframes())


def wav_rate(b64: str) -> int:
    with wave.open(io.BytesIO(base64.b64decode(b64)), "rb") as wf:
        return wf.getframerate()


async def run():
    print("\n" + "=" * 64)
    print("Live AUDIO-IN regression — real PCM streamed to /ws/live/")
    print("=" * 64)

    print(f"\n[1] Synthesizing speech: {UTTERANCE!r}")
    try:
        pcm = await synth_pcm_16k(UTTERANCE)
    except Exception as e:
        print(f"    Could not synthesize via Google Cloud TTS: {type(e).__name__}: {e}")
        print("    (Test needs Journey TTS creds to fabricate mic audio.)")
        sys.exit(2)

    dur_s = len(pcm) / 2 / 16000
    print(f"    PCM bytes={len(pcm):,} duration={dur_s:.2f}s (push-to-talk, no trailing silence)")

    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(f"{BASE_URL}/api/contracts/analyze", data={"text": CONTRACT})
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"    session={sid[:8]}…")

    ws_url = f"{WS_BASE}/ws/live/{sid}"
    chunk_bytes = int(16000 * 2 * CHUNK_MS / 1000)

    sent = 0
    audio_chunks = 0
    first_audio = None
    closed_early = False
    transcripts = []
    t0 = time.monotonic()

    async with websockets.connect(ws_url, max_size=20 * 1024 * 1024) as ws:
        for _ in range(6):
            try:
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
                if ev.get("type") == "sentence":
                    break
            except asyncio.TimeoutError:
                break

        async def feed_audio():
            nonlocal sent
            for off in range(0, len(pcm), chunk_bytes):
                if ws.state.name != "OPEN":
                    return
                frame = pcm[off:off + chunk_bytes]
                await ws.send(json.dumps({
                    "type": "audio_input",
                    "audio": base64.b64encode(frame).decode(),
                }))
                sent += 1
                await asyncio.sleep(CHUNK_MS / 1000)  

        async def feed_then_end():
            await feed_audio()
            if ws.state.name == "OPEN":
                await ws.send(json.dumps({"type": "end_audio_turn"}))
                print(f"    end_audio_turn sent after {sent} chunks")

        feeder = asyncio.create_task(feed_then_end())

        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                if feeder.done() and audio_chunks > 0:
                    break
                continue
            except websockets.ConnectionClosed as e:
                print(f"    CONNECTION CLOSED: code={e.code} reason={e.reason!r} (sent={sent})")
                closed_early = True
                break
            ev = json.loads(raw)
            t = ev.get("type")
            if t == "audio_chunk":
                audio_chunks += 1
                if first_audio is None:
                    first_audio = round(time.monotonic() - t0, 2)
                    print(f"    first audio_chunk @ {first_audio}s | {wav_rate(ev['audio'])}Hz")
            elif t == "sentence":
                transcripts.append(ev.get("text", ""))
            elif t == "audio_done":
                if audio_chunks:
                    break
            elif t == "error":
                print(f"    ERROR event: {ev.get('message')}")

        feeder.cancel()

    print("\n" + "=" * 64)
    print("RESULT")
    print("=" * 64)
    print(f"  audio_input chunks sent : {sent}")
    print(f"  Session survived chunk#1: {not (closed_early and sent <= 2)}")
    print(f"  audio_chunk(s) received : {audio_chunks}")
    print(f"  first audio             : {first_audio}s")
    if transcripts:
        print(f"  model said              : {' '.join(transcripts)[:160]}")
    survived = sent > 5 and not closed_early
    responded = audio_chunks > 0
    print(f"\n  VERDICT: {'PASS — audio-in accepted & model replied with audio' if (survived and responded) else ('PARTIAL — audio-in accepted, no model audio' if survived else 'FAIL — session died on audio-in')}")


if __name__ == "__main__":
    asyncio.run(run())
