"""Tolerant JSON extraction from LLM free-text replies."""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json(text: str) -> Any:
    """Parse a JSON object from model output, tolerating prose or ```json fences."""
    if text is None:
        raise ValueError("empty response content")
    text = text.strip()
    if not text:
        raise ValueError("empty response content")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fence.group(1).strip() if fence else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} span.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        return json.loads(candidate[start:end + 1])
    raise ValueError(f"no JSON object found in response: {text[:200]!r}")
