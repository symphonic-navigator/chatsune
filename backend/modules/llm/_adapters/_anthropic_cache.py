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
# sonnet / opus token at a word boundary. Older "claude-instant-*"
# slugs deliberately do not match — they predate cache_control
# support, so the negative case is correct behaviour.
# ``[^/]*`` (not ``.*``) bounds the wildcard inside the slug tail.
# ``rsplit("/", 1)[-1]`` already strips any path prefix, so the tail
# cannot contain ``/`` — the bounded form keeps regex evaluation
# linear regardless of slug length.
_CLAUDE_RE = re.compile(r"claude[^/]*\b(haiku|sonnet|opus)\b", re.IGNORECASE)


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
    messages: list[CompletionMessage], ttl: CacheTtl,
) -> list[CacheMarker]:
    """Compute marker positions for an Anthropic-compatible request.

    Strategy (see spec §5.2):

    * **System** marker at index 0 if the first message is a system
      message — always 1h, regardless of the user's TTL choice.
    * **Block-boundary** marker at the last crossed BLOCK_SIZE-aligned
      message index — always 1h. Provides a long-pause fallback that
      survives 5m idle periods even in 5m-mode.
    * **Rolling tail** marker at ``len(messages) - 2`` (the last
      stable assistant turn boundary) — TTL = the user's choice.

    The 4th breakpoint slot is deliberately unused (spec §11).

    Returns an empty list for ``ttl == "off"`` or empty inputs. Marker
    list is in ascending message-index order.
    """
    if ttl == "off" or not messages:
        return []

    markers: list[CacheMarker] = []

    if messages[0].role == "system":
        markers.append(CacheMarker(message_index=0, ttl="1h"))

    n = len(messages)
    last_block_end = (n // BLOCK_SIZE) * BLOCK_SIZE - 1
    if last_block_end > 0 and last_block_end < n - 1:
        if not any(m.message_index == last_block_end for m in markers):
            markers.append(
                CacheMarker(message_index=last_block_end, ttl="1h"),
            )

    if n >= 2:
        tail_index = n - 2
        if tail_index > 0 and not any(
            m.message_index == tail_index for m in markers
        ):
            markers.append(CacheMarker(message_index=tail_index, ttl=ttl))

    return markers
