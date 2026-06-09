"""
SentenceBuffer — accumulates Gemini streaming text tokens and emits complete sentences.

Goal: low perceived latency for the voice agent.
  - Gemini streams tokens one by one.
  - This buffer collects them and emits a complete sentence as soon as a boundary appears.
  - The frontend receives each sentence and immediately passes it to speechSynthesis.

Sentence boundaries: .  ?  !  ،  ؟  (Arabic punctuation included)

Phase 5: full implementation with edge-case handling
  (abbreviations like "Dr.", decimal numbers "3.14", ellipsis "...", etc.)
"""
import re
from typing import List

_BOUNDARY = re.compile(r"(?<=[.!?،؟])\s+")


class SentenceBuffer:
    """
    Accumulates text. Call add_token() for each streaming chunk.
    Call flush() at stream end to emit any remaining text.
    """

    def __init__(self):
        self._buffer = ""

    def add_token(self, token: str) -> List[str]:
        """Add a token and return any complete sentences ready to speak."""
        self._buffer += token
        return self._extract()

    def flush(self) -> List[str]:
        """Return any remaining buffered text as a final sentence."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return [remaining] if remaining else []

    def reset(self) -> None:
        self._buffer = ""

    def _extract(self) -> List[str]:
        parts = _BOUNDARY.split(self._buffer)
        if len(parts) <= 1:
            return []
        complete, self._buffer = parts[:-1], parts[-1]
        return [s.strip() for s in complete if s.strip()]
