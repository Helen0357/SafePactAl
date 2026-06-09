"""
Developer utility — list available Gemini models for the configured API key.

Usage (run from the backend/ directory):
    python -m app.utils.model_check

Use the output to set the correct model IDs in backend/.env:
    GEMINI_ANALYSIS_MODEL=    <- choose a pro-level model
    GEMINI_CONVERSATION_MODEL= <- choose a flash-level model
    GEMINI_LIVE_MODEL=         <- choose a live/audio model (Phase 5, optional)
"""
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def list_available_models() -> None:
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).parent.parent.parent / ".env")
    except ImportError:
        pass

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.error(
            "GEMINI_API_KEY is not set.\n"
            "Add it to backend/.env before running this utility."
        )
        sys.exit(1)

    try:
        from google import genai
    except ImportError:
        logger.error(
            "google-genai is not installed.\n"
            "Run: pip install google-genai"
        )
        sys.exit(1)

    logger.info("Connecting to Google AI Studio…")
    try:
        client = genai.Client(api_key=api_key)
        models = list(client.models.list())
    except Exception as exc:
        logger.error("Failed to list models: %s", exc)
        sys.exit(1)

    if not models:
        logger.warning("No models returned. Check your API key and quota.")
        return

    logger.info("\n%s", "=" * 60)
    logger.info("Available Gemini models (%d total)", len(models))
    logger.info("=" * 60)

    for model in models:
        name = getattr(model, "name", str(model))
        display = getattr(model, "display_name", "")
        methods = getattr(model, "supported_generation_methods", [])
        logger.info("\n  %-50s", name)
        if display:
            logger.info("  Display : %s", display)
        if methods:
            logger.info("  Methods : %s", ", ".join(methods))

    logger.info("\n%s", "=" * 60)
    logger.info(
        "Set these in backend/.env:\n"
        "  GEMINI_ANALYSIS_MODEL=<pro-level name above>\n"
        "  GEMINI_CONVERSATION_MODEL=<flash-level name above>\n"
        "  GEMINI_LIVE_MODEL=<live/audio model, or leave blank>\n"
    )


if __name__ == "__main__":
    list_available_models()
