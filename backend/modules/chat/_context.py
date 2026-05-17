import math
from dataclasses import dataclass
from typing import Literal


@dataclass
class ContextBudget:
    max_context_tokens: int
    system_prompt_tokens: int
    tool_definition_tokens: int
    safety_reserve: int
    response_reserve: int
    available_for_chat: int


def calculate_budget(
    max_context_tokens: int,
    system_prompt_tokens: int,
    new_message_tokens: int,
    tool_definition_tokens: int = 0,
) -> ContextBudget:
    """Calculate the token budget for chat message selection."""
    safety_reserve = math.floor(max_context_tokens * 0.165)
    response_reserve = 1000 + new_message_tokens
    available = (
        max_context_tokens
        - safety_reserve
        - system_prompt_tokens
        - tool_definition_tokens
        - response_reserve
    )
    return ContextBudget(
        max_context_tokens=max_context_tokens,
        system_prompt_tokens=system_prompt_tokens,
        tool_definition_tokens=tool_definition_tokens,
        safety_reserve=safety_reserve,
        response_reserve=response_reserve,
        available_for_chat=max(0, available),
    )


def select_message_pairs(
    messages: list[dict],
    available_tokens: int,
) -> tuple[list[dict], int]:
    """Select message pairs by ``correlation_id`` within budget.

    Pairs a user message with the assistant message that shares its
    ``correlation_id``. Assistant messages with ``status != "completed"``
    cause their pair to be dropped entirely (the user message goes too
    — the turn produced no usable reply, and sending the user without
    a reply would break every adapter's prompt contract).

    Replaces the previous position-based algorithm; see spec
    ``devdocs/specs/2026-05-17-pair-by-correlation-design.md``. Solves:

    * a-2: orphan user (assistant aborted/dropped) is no longer
      silently swept past — it's simply not paired.
    * a-3: two-tab race where user_B lands between user_A and the
      cancelled assistant-for-A. With correlation_id pairing the
      builder matches user_B with the completed-assistant-for-B
      regardless of write order.
    * a-10: aborted user messages do not pollute downstream context.

    Returns ``(selected_messages_in_chronological_order, total_tokens)``.
    """
    # 1. Index by correlation_id.
    by_corr: dict[str, dict] = {}  # cid -> {"user": doc, "assistant": doc}
    user_order: list[dict] = []  # user messages in their original order

    for m in messages:
        cid = m.get("correlation_id")
        if not cid:
            # Defensive: legacy doc whose backfill migration has not
            # run, or a synthetic-orphan id was deliberately omitted.
            # Pair-matching requires a key — skip silently.
            continue
        slot = by_corr.setdefault(cid, {})
        if m["role"] == "user":
            # Last-write-wins on the user slot (regenerate/edit may
            # overwrite an earlier user doc carrying the same cid).
            if "user" not in slot:
                user_order.append(m)
            slot["user"] = m
        elif m["role"] == "assistant":
            # Last-write-wins on the assistant slot too — regenerate
            # produces a new assistant doc with the same cid.
            slot["assistant"] = m

    # 2. Build complete pairs in original order.
    pairs: list[tuple[dict, dict]] = []
    for user_msg in user_order:
        cid = user_msg["correlation_id"]
        slot = by_corr[cid]
        asst = slot.get("assistant")
        if asst is None:
            # Orphan user (cancelled before reply, retracted, or split
            # across an import) — drop.
            continue
        if asst.get("status") != "completed":
            # Aborted, refused, errored — drop the whole pair.
            continue
        pairs.append((user_msg, asst))

    # 3. Newest-first budget selection.
    selected_pairs: list[tuple[dict, dict]] = []
    total_tokens = 0

    for pair in reversed(pairs):
        pair_tokens = pair[0]["token_count"] + pair[1]["token_count"]
        if total_tokens + pair_tokens > available_tokens:
            continue
        selected_pairs.append(pair)
        total_tokens += pair_tokens

    selected_pairs.reverse()

    result: list[dict] = []
    for user_msg, assistant_msg in selected_pairs:
        result.append(user_msg)
        result.append(assistant_msg)

    return result, total_tokens


def get_ampel_status(fill_ratio: float) -> Literal["green", "yellow", "orange", "red"]:
    """Return the context ampel status based on fill ratio (0.0 to 1.0).

    Thresholds:
      green  — below 50%: plenty of room
      yellow — 50-65%: should consider synopsis soon
      orange — 65-80%: urgent, synopsis recommended now
      red    — 80%+: synopsis no longer viable (approaching autocompact at 83.5%)
    """
    if fill_ratio >= 0.80:
        return "red"
    if fill_ratio >= 0.65:
        return "orange"
    if fill_ratio >= 0.50:
        return "yellow"
    return "green"
