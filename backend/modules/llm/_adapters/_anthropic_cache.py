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
