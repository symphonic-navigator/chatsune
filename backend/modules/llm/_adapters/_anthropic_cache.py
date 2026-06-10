"""Anthropic prompt-cache strategy library.

Pure functions that decide whether a given model accepts Anthropic
``cache_control`` markers and where those markers should be placed
in a chat message list. Used by both the OpenRouter and nano-gpt
adapters, which translate the resulting positions into OpenAI-compat
``cache_control`` content-block dicts at request time.

Spec: devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from shared.dtos.inference import CompletionMessage

# Match "claude" anywhere in the slug tail, followed by a haiku /
# sonnet / opus / fable token at a word boundary. Older
# "claude-instant-*" slugs deliberately do not match — they predate
# cache_control support, so the negative case is correct behaviour.
# ``[^/]*`` (not ``.*``) bounds the wildcard inside the slug tail.
# ``rsplit("/", 1)[-1]`` already strips any path prefix, so the tail
# cannot contain ``/`` — the bounded form keeps regex evaluation
# linear regardless of slug length.
_CLAUDE_RE = re.compile(r"claude[^/]*\b(haiku|sonnet|opus|fable)\b", re.IGNORECASE)


def is_anthropic_model(model_id: str) -> bool:
    """True iff ``model_id`` looks like a Claude model that accepts cache_control.

    Tolerant of router-specific slug shapes:

    * OpenRouter: ``anthropic/claude-…`` and the occasional
      ``~anthropic/claude-…`` (latter prefix observed on the OR
      catalogue, semantics unclear but harmless).
    * nano-gpt:   ``claude-3-7-sonnet-20250219`` (no vendor prefix).

    Strategy: take only the part after the last ``/`` (or the whole
    string if no ``/`` is present), then regex-match for
    ``claude.*haiku|sonnet|opus``.
    """
    tail = model_id.rsplit("/", 1)[-1]
    return bool(_CLAUDE_RE.search(tail))


# Subset of _CLAUDE_RE — same bounded-wildcard rationale; fable family only.
_EFFORT_BASED_CLAUDE_RE = re.compile(r"claude[^/]*\bfable\b", re.IGNORECASE)


def is_effort_based_claude(model_id: str) -> bool:
    """True iff ``model_id`` is a Claude model with effort-based thinking.

    Fable-family models do not start thinking on ``enabled: true``
    alone — the router silently returns a plain completion unless an
    ``effort`` value is present. They therefore bypass the INS-037
    effort omission. Effort is verified cache-safe on these routes;
    see devdocs/specs/2026-06-10-claude-fable-5-nano-gpt-design.md
    and INS-055.
    """
    tail = model_id.rsplit("/", 1)[-1]
    return bool(_EFFORT_BASED_CLAUDE_RE.search(tail))


CacheTtl = Literal["off", "5m", "1h"]
BlockTtl = Literal["5m", "1h"]

# Block-boundary stride. Static first-guess; observability data
# (see spec §10) drives any future re-tuning. One-line change, no
# migration impact — see spec §11.
BLOCK_SIZE = 8


@dataclass(frozen=True)
class CacheMarker:
    """Where to place a cache_control marker and at what TTL.

    ``message_index`` is the index into ``CompletionRequest.messages``
    of the message whose final content block carries the marker.
    """

    message_index: int
    ttl: BlockTtl


def compute_cache_markers(
    messages: list[CompletionMessage],
    ttl: CacheTtl,
    *,
    compact_anchor_index: int | None = None,
) -> list[CacheMarker]:
    """Compute marker positions for an Anthropic-compatible request.

    When ``compact_anchor_index`` is set (i.e. the session carries an
    active compaction checkpoint), marker 2 sits at that index instead
    of the heuristic block boundary. See spec
    devdocs/specs/2026-05-15-compact-and-continue-design.md §6.10.
    """
    if ttl == "off" or not messages:
        return []

    markers: list[CacheMarker] = []

    if messages[0].role == "system":
        markers.append(CacheMarker(message_index=0, ttl="1h"))

    if compact_anchor_index is not None and 0 <= compact_anchor_index < len(messages):
        if not any(m.message_index == compact_anchor_index for m in markers):
            markers.append(CacheMarker(message_index=compact_anchor_index, ttl="1h"))
    else:
        n = len(messages)
        last_block_end = (n // BLOCK_SIZE) * BLOCK_SIZE - 1
        if last_block_end > 0 and last_block_end < n - 1:
            if not any(m.message_index == last_block_end for m in markers):
                markers.append(
                    CacheMarker(message_index=last_block_end, ttl="1h"),
                )

    n = len(messages)
    if n >= 2:
        tail_index = n - 2
        if tail_index > 0 and not any(
            m.message_index == tail_index for m in markers
        ):
            markers.append(CacheMarker(message_index=tail_index, ttl=ttl))

    return markers


def extract_cache_metrics(usage: dict) -> tuple[int, int]:
    """Pull (cache_read, cache_creation) tokens from a usage dict.

    Two upstream schemas have been observed in the wild:

    * **Anthropic-native** (direct API or some passthroughs):
      top-level ``cache_read_input_tokens`` and
      ``cache_creation_input_tokens``.
    * **OpenRouter / OpenAI-compat**: nested under
      ``prompt_tokens_details`` as ``cached_tokens`` (read) and
      ``cache_write_tokens`` (creation).

    Tries the Anthropic-native fields first; falls back to the nested
    OR-style fields. Returns ``(0, 0)`` when neither schema is
    populated. Returns ints — usage values are always integer token
    counts in both schemas.
    """
    read = int(usage.get("cache_read_input_tokens") or 0)
    creation = int(usage.get("cache_creation_input_tokens") or 0)
    if read or creation:
        return read, creation

    details = usage.get("prompt_tokens_details") or {}
    return (
        int(details.get("cached_tokens") or 0),
        int(details.get("cache_write_tokens") or 0),
    )
