"""
TTS service — Phase 8C: Google Cloud TTS Journey voice (primary) + Gemini TTS (fallback).

Primary   — Google Cloud TTS, en-US-Journey-D (~200-400ms latency).
            Auth via GOOGLE_APPLICATION_CREDENTIALS env var (service account JSON).
Fallback  — Gemini TTS, Charon voice (~5-10s latency), API key auth.

Zero disk I/O. All synthesis in memory. Returns WAV bytes or None on failure.
"""
import base64
import io
import logging
import wave
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SAMPLE_RATE  = 24_000
_CHANNELS     = 1
_SAMPLE_WIDTH = 2  

_GCP_DEFAULT_VOICE   = "en-US-Journey-D"   
_GCP_DEFAULT_LANG    = "en-US"
_GCP_SPEAKING_RATE   = 1.05             

_gcp_client: Optional[Any] = None

_GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_GEMINI_TTS_VOICE = "Charon"



def _pcm_to_wav(pcm_bytes: bytes) -> bytes:
    """Wrap raw PCM bytes in a WAV container. In-memory only, no disk writes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def wav_duration_ms(wav_bytes: bytes) -> int:
    """Return exact playback duration of a WAV file in milliseconds."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return int(wf.getnframes() / wf.getframerate() * 1000)


def _get_gcp_client() -> Any:
    """Return cached async Cloud TTS client (created once per process)."""
    global _gcp_client
    if _gcp_client is None:
        from google.cloud import texttospeech
        _gcp_client = texttospeech.TextToSpeechAsyncClient()
    return _gcp_client



async def _synthesize_google_cloud_journey(
    text: str,
    voice_name: str = _GCP_DEFAULT_VOICE,
    language_code: str = _GCP_DEFAULT_LANG,
) -> Optional[bytes]:
    """
    Google Cloud TTS with Journey voice (~200-400ms).
    Reads GOOGLE_APPLICATION_CREDENTIALS env var for auth (set at startup).
    Returns WAV bytes or None on failure.
    """
    import os
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        logger.debug("GOOGLE_APPLICATION_CREDENTIALS not set — skipping GCP TTS")
        return None
    try:
        from google.cloud import texttospeech

        client = _get_gcp_client()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice_params = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=_SAMPLE_RATE,
            speaking_rate=_GCP_SPEAKING_RATE,
        )
        response = await client.synthesize_speech(
            input=synthesis_input,
            voice=voice_params,
            audio_config=audio_config,
        )
        wav = _pcm_to_wav(response.audio_content)
        logger.debug(
            "GCP Journey TTS ok — %d chars -> %d wav bytes (%dms)",
            len(text), len(wav), wav_duration_ms(wav),
        )
        return wav
    except Exception as exc:
        logger.error("Google Cloud Journey TTS failed: %s", exc)
        return None



async def _synthesize_gemini(text: str, api_key: str) -> Optional[bytes]:
    """Gemini TTS fallback (~5-10s per sentence). Returns WAV bytes or None."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=_GEMINI_TTS_VOICE,
                    )
                )
            ),
        )
        response = await client.aio.models.generate_content(
            model=_GEMINI_TTS_MODEL,
            contents=text,
            config=config,
        )
        pcm = response.candidates[0].content.parts[0].inline_data.data
        if isinstance(pcm, str):  
            pcm = base64.b64decode(pcm)
        wav = _pcm_to_wav(pcm)
        logger.debug("Gemini TTS ok — %d chars -> %d wav bytes", len(text), len(wav))
        return wav
    except Exception as exc:
        logger.error("Gemini TTS failed: %s", exc)
        return None



async def synthesize_speech_fast(
    text: str,
    google_cloud_api_key: str = "",  
    gemini_api_key: str = "",
    voice_name: str = _GCP_DEFAULT_VOICE,
    language_code: str = _GCP_DEFAULT_LANG,
) -> Optional[bytes]:
    """
    Primary TTS entry point.
    1. Google Cloud TTS Journey voice (~300ms) — if GOOGLE_APPLICATION_CREDENTIALS set.
    2. Gemini TTS Charon voice (~8s)           — fallback when GCP unavailable.
    Returns WAV bytes, or None if both providers fail.
    """
    result = await _synthesize_google_cloud_journey(
        text, voice_name=voice_name, language_code=language_code
    )
    if result:
        return result

    if gemini_api_key:
        logger.info("GCP TTS unavailable — falling back to Gemini TTS for seq")
        return await _synthesize_gemini(text, gemini_api_key)

    logger.error(
        "No TTS provider available. "
        "Set GOOGLE_APPLICATION_CREDENTIALS or GEMINI_API_KEY."
    )
    return None


async def synthesize_speech(text: str, api_key: str) -> Optional[bytes]:
    """Legacy alias — Gemini TTS only. Prefer synthesize_speech_fast."""
    return await _synthesize_gemini(text, api_key)
