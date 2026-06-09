from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Google AI Studio ──────────────────────────────────
    gemini_api_key: str = ""
    gemini_analysis_model: str = ""
    gemini_conversation_model: str = ""
    gemini_live_model: str = "gemini-2.5-flash-native-audio-latest"

    voice_fallback_model: str = "gemini-2.5-flash-lite"

    # ── Google Cloud TTS — service account (Phase 8C) ────────

    google_application_credentials: str = ""
    google_cloud_tts_voice: str = "en-US-Journey-D"   
    google_cloud_tts_language: str = "en-US"
    tts_provider: str = "google_cloud"   
  
    google_cloud_tts_arabic_voice: str = ""
    google_cloud_tts_arabic_language: str = "ar-XA"

    tts_chunk_timeout_seconds: float = 8.0

    google_cloud_tts_api_key: str = ""

    # ── Application ───────────────────────────────────────
    app_name: str = "ProtectMe AI"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # ── CORS ──────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    backend_cors_origins: str = ""

    # ── Session ───────────────────────────────────────────
    session_ttl_minutes: int = 60

    # ── Derived properties ────────────────────────────────
    @property
    def cors_origins(self) -> list[str]:
        """Allowed CORS origins. Uses BACKEND_CORS_ORIGINS (comma-separated) when
        set, otherwise falls back to FRONTEND_URL. localhost:3000 is always
        included so a default local dev frontend works out of the box."""
        if self.backend_cors_origins.strip():
            origins = [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]
        else:
            origins = [self.frontend_url]
        if "http://localhost:3000" not in origins:
            origins.append("http://localhost:3000")
        return origins

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def missing_required_vars(self) -> list[str]:
        missing = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.gemini_analysis_model:
            missing.append("GEMINI_ANALYSIS_MODEL")
        if not self.gemini_conversation_model:
            missing.append("GEMINI_CONVERSATION_MODEL")
        return missing

    @property
    def configuration_warnings(self) -> list[str]:
        missing = self.missing_required_vars
        if not missing:
            return []
        return [
            f"Missing environment variables: {', '.join(missing)}. "
            "Copy backend/.env.example to backend/.env and fill in the values. "
            "Run 'python -m app.utils.model_check' to find available model IDs."
        ]


settings = Settings()
