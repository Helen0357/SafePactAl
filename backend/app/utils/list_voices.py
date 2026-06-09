"""
List available Google Cloud Text-to-Speech voices, optionally filtered by a
language-code prefix.

Usage (from the backend/ directory, with .env configured):
    python -m app.utils.list_voices          # all voices
    python -m app.utils.list_voices ar       # Arabic (ar-XA) voices
    python -m app.utils.list_voices en-US    # US English voices

Requires GOOGLE_APPLICATION_CREDENTIALS (resolved from .env the same way the app
does at startup). Prints: language_code  voice_name  gender  sample_rate.

Use this to pick a verified ar-XA voice for GOOGLE_CLOUD_TTS_ARABIC_VOICE.
"""
import os
import sys
from pathlib import Path

from app.core.config import settings


def _ensure_credentials() -> None:
    """Resolve GOOGLE_APPLICATION_CREDENTIALS from settings (relative to backend/)."""
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return
    if settings.google_application_credentials:
        creds = Path(settings.google_application_credentials)
        if not creds.is_absolute():
            backend_root = Path(__file__).parent.parent.parent  # app/utils -> app -> backend
            creds = (backend_root / creds).resolve()
        if creds.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds)


def list_voices(prefix: str = "") -> list[tuple[str, str, str, int]]:
    """Return [(language_code, voice_name, gender, sample_rate), ...] filtered by prefix."""
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    response = client.list_voices()
    rows: list[tuple[str, str, str, int]] = []
    for v in response.voices:
        for lc in v.language_codes:
            if not prefix or lc.lower().startswith(prefix.lower()):
                rows.append((lc, v.name, v.ssml_gender.name, v.natural_sample_rate_hertz))
    rows.sort()
    return rows


def main() -> None:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    _ensure_credentials()
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("ERROR: GOOGLE_APPLICATION_CREDENTIALS not set (check backend/.env and .secrets/).")
        sys.exit(1)
    try:
        rows = list_voices(prefix)
    except Exception as exc:  
        print(f"ERROR listing voices: {exc}")
        sys.exit(1)
    if not rows:
        print(f"No voices found for prefix '{prefix}'.")
        return
    print(f"{'LANGUAGE':10} {'VOICE NAME':28} {'GENDER':8} RATE")
    for lc, name, gender, rate in rows:
        print(f"{lc:10} {name:28} {gender:8} {rate}")
    print(f"\n{len(rows)} voice(s).")


if __name__ == "__main__":
    main()
