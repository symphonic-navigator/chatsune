"""Tolerant JSON parser for LLM extraction output.

Handles: markdown fences, trailing commas, missing fields, broken arrays,
and individual JSON objects on separate lines. Returns a list of normalised
entry dicts with guaranteed 'content', 'category', and 'is_correction' keys.
"""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def parse_extraction_output(raw: str | None) -> list[dict]:
    """Parse LLM extraction output into a list of normalised entry dicts.

    Returns an empty list when the input is unparseable.
    """
    if not raw or not raw.strip():
        return []

    text = raw.strip()

    # Step 1: strip markdown code fences
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Step 2: try direct JSON parse (with trailing comma repair)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [_normalise(entry) for entry in parsed if isinstance(entry, dict) and "content" in entry]
        if isinstance(parsed, dict) and "content" in parsed:
            return [_normalise(parsed)]
    except (json.JSONDecodeError, TypeError):
        pass

    # Step 3: fallback — extract individual JSON objects via regex
    entries: list[dict] = []
    for match in _OBJECT_RE.finditer(text):
        fragment = _TRAILING_COMMA_RE.sub(r"\1", match.group())
        try:
            obj = json.loads(fragment)
            if isinstance(obj, dict) and "content" in obj:
                entries.append(_normalise(obj))
        except (json.JSONDecodeError, TypeError):
            continue

    return entries


def _normalise(entry: dict) -> dict:
    """Ensure required keys exist with sensible defaults."""
    return {
        "content": str(entry.get("content", "")),
        "category": entry.get("category"),
        "is_correction": bool(entry.get("is_correction", False)),
    }
