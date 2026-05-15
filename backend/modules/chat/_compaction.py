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
