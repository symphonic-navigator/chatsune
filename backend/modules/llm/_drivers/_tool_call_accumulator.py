"""Accumulator for OpenAI-style streaming tool-call fragments.

Used by driver-layer parsers when the upstream router (OpenRouter, Novita,
nano-gpt) streams tool-calls incrementally — first chunk has the
``{index, id, type, function: {name, arguments}}`` header with empty args,
subsequent chunks only the ``arguments`` string fragments. Idempotent
``finalised()``: subsequent calls return an empty list.

This duplicates ``_openrouter_http._ToolCallAccumulator`` to avoid the
driver layer importing adapter internals (per the Driver-Layer spec
boundary). A future refactor pass may consolidate.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4


class ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    ``finalised()`` is idempotent: subsequent calls return an empty list.
    Some upstream providers (notably DeepSeek via OpenRouter) may emit two
    chunks with ``finish_reason="tool_calls"`` for the same call;
    finalising once and remembering the result avoids duplicate downstream
    events.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, Any]] = {}
        self._finalised = False

    def ingest(self, fragments: list[dict[str, Any]]) -> None:
        for frag in fragments:
            idx = frag.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(idx, {
                "id": None, "name": "", "args": "",
            })
            if frag.get("id"):
                slot["id"] = frag["id"]
            fn = frag.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    def finalised(self) -> list[dict[str, Any]]:
        if self._finalised:
            return []
        self._finalised = True
        calls: list[dict[str, Any]] = []
        for idx, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
                "index": idx,
            })
        return calls
