"""Pure helpers for chat compaction (no IO, no LLM calls).

The job handler in backend/jobs/handlers/_chat_compaction.py composes
these functions with the repository, the LLM client, and the event bus.
"""

from __future__ import annotations


_MIN_TAIL_MESSAGES = 12      # 6 turns
_TAIL_TOKEN_FRACTION = 0.20  # 20 % of model context


def determine_tail_start_index(
    messages: list[dict], *, model_context: int,
) -> int:
    """Return the index of the first message that must stay in the tail.

    Walks newest → oldest, accumulating ``token_count``. The tail extends
    until BOTH the 6-turn floor (12 messages) AND the 20% token rule are
    satisfied — i.e. whichever rule yields the LARGER tail wins.
    """
    if not messages:
        return 0

    total = len(messages)
    token_budget = int(model_context * _TAIL_TOKEN_FRACTION)

    tail_tokens = 0
    chosen_idx = total
    for i in range(total - 1, -1, -1):
        tail_tokens += int(messages[i].get("token_count") or 0)
        tail_messages = total - i
        if tail_messages >= _MIN_TAIL_MESSAGES and tail_tokens >= token_budget:
            chosen_idx = i
            break
        chosen_idx = i

    return max(0, chosen_idx)


def select_source_range(
    messages: list[dict],
    *,
    tail_start_index: int,
    prev_tail_start_id: str | None,
) -> tuple[list[dict], list[dict]]:
    """Split messages into source range (to be compacted) and tail.

    When ``prev_tail_start_id`` is provided, the source begins at that
    message (re-compact case: only the messages added since the previous
    checkpoint are condensed; the previous compact-markdown is folded in
    as Previous Story by the prompt builder).
    """
    tail = messages[tail_start_index:]
    if prev_tail_start_id is None:
        source = messages[:tail_start_index]
    else:
        start = next(
            (i for i, m in enumerate(messages) if m["_id"] == prev_tail_start_id),
            0,
        )
        source = messages[start:tail_start_index]
    return source, tail


def sanitise_source(source: list[dict]) -> list[dict]:
    """Drop tool-role messages and assistant messages with empty content
    (which are typically pure tool-call wrappers). Keeps user and
    text-bearing assistant messages."""
    cleaned: list[dict] = []
    for m in source:
        role = m.get("role")
        if role == "tool":
            continue
        if role == "assistant" and not (m.get("content") or "").strip():
            continue
        cleaned.append(m)
    return cleaned
