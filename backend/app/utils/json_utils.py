import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_json_from_text(text: str) -> Optional[dict]:
    """
    Extract a JSON object from a Gemini response that may include prose or
    markdown code fences (```json ... ```).
    Returns None if no valid JSON is found.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for pattern in (r"```(?:json)?\s*([\s\S]+?)\s*```", r"`([\s\S]+?)`"):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Could not extract JSON from Gemini response (first 300 chars): %s", text[:300])
    return None


def safe_dumps(obj: Any, **kwargs) -> str:
    """JSON-serialize with sensible defaults (non-ASCII preserved, dates as strings)."""
    return json.dumps(obj, ensure_ascii=False, default=str, **kwargs)
