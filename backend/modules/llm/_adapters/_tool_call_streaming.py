"""Helper for streaming OpenAI-style tool-call fragments through the
adapter layer as ``ToolCallArgsDelta`` events.

Used by every OpenAI-compatible adapter (xAI, Mistral, Community,
OpenRouter, nano-gpt, Tensorix, Novita). Anthropic models flow through
OpenRouter/nano-gpt and arrive in OpenAI-shaped fragments, so they
share this code path.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ToolCallArgsDelta


def fragments_to_delta_events(
    fragments: list[dict[str, Any]],
    acc: Any,
) -> list[ToolCallArgsDelta]:
    """Map raw OpenAI-style tool_call fragments to ``ToolCallArgsDelta``
    events and feed them into ``acc`` for final accumulation.

    Order of operations: build events first (reading current accumulator
    state for id/name resolution), then ``acc.ingest(fragments)``. This
    way each emitted event reflects the fragment AS SEEN, not the
    post-ingest state, which matters when a single fragment supplies a
    previously-unknown id or name.

    ``acc`` is duck-typed against ``_ToolCallAccumulator`` defined in the
    adapter modules. The helper only reads ``acc._by_index`` and calls
    ``acc.ingest()`` — both stable parts of the contract.
    """
    events: list[ToolCallArgsDelta] = []
    # Track id/name discovered within this batch so later fragments in the
    # same batch can inherit them even before ``acc.ingest`` is called.
    seen_ids: dict[int, str | None] = {}
    seen_names: dict[int, str | None] = {}
    for frag in fragments:
        idx = frag.get("index")
        if idx is None:
            continue
        fn = frag.get("function") or {}
        existing = acc._by_index.get(idx, {})
        resolved_id = (
            frag.get("id") or seen_ids.get(idx) or existing.get("id")
        )
        resolved_name = (
            fn.get("name") or seen_names.get(idx) or existing.get("name") or None
        )
        if resolved_id is not None:
            seen_ids[idx] = resolved_id
        if resolved_name is not None:
            seen_names[idx] = resolved_name
        args_fragment = fn.get("arguments") or ""
        if args_fragment or frag.get("id") or fn.get("name"):
            events.append(ToolCallArgsDelta(
                index=idx,
                id=resolved_id,
                name=resolved_name,
                arguments_delta=args_fragment,
            ))
    acc.ingest(fragments)
    return events
