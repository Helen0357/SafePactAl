import logging
import re
from typing import List

logger = logging.getLogger(__name__)

MAX_CONTRACT_CHARS = 500_000


def truncate_contract_text(text: str, max_chars: int = MAX_CONTRACT_CHARS) -> str:
    """Truncate contract text to fit within safe context limits."""
    if len(text) <= max_chars:
        return text
    logger.warning(
        "Contract text truncated from %d to %d characters.",
        len(text), max_chars,
    )
    return text[:max_chars] + "\n\n[Document truncated due to length.]"


def clean_contract_text(text: str) -> str:
    """Normalize whitespace and remove null bytes."""
    text = text.replace("\x00", "")
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r" {3,}", "  ", text)
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    """
    Split text on sentence boundaries for TTS streaming.
    Full implementation lives in agent/streaming/sentence_buffer.py (Phase 5).
    """
    pattern = re.compile(r"(?<=[.!?،؟])\s+")
    parts = pattern.split(text)
    return [s.strip() for s in parts if s.strip()]
