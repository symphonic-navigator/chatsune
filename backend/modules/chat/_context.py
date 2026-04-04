import math
from dataclasses import dataclass
from typing import Literal


@dataclass
class ContextBudget:
    max_context_tokens: int
    system_prompt_tokens: int
    safety_reserve: int
    response_reserve: int
    available_for_chat: int


def calculate_budget(
    max_context_tokens: int,
    system_prompt_tokens: int,
    new_message_tokens: int,
) -> ContextBudget:
    """Calculate the token budget for chat message selection."""
    safety_reserve = math.floor(max_context_tokens * 0.165)
    response_reserve = 1000 + new_message_tokens
    available = max_context_tokens - safety_reserve - system_prompt_tokens - response_reserve
    return ContextBudget(
        max_context_tokens=max_context_tokens,
        system_prompt_tokens=system_prompt_tokens,
        safety_reserve=safety_reserve,
        response_reserve=response_reserve,
        available_for_chat=max(0, available),
    )


def select_message_pairs(
    messages: list[dict],
    available_tokens: int,
) -> tuple[list[dict], int]:
    """Select message pairs from newest to oldest within budget.

    Messages are grouped into (user, assistant) pairs.
    Returns (selected_messages_in_chronological_order, total_tokens).
    """
    # Group into pairs
    pairs: list[tuple[dict, dict]] = []
    i = 0
    while i + 1 < len(messages):
        if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
            pairs.append((messages[i], messages[i + 1]))
            i += 2
        else:
            i += 1

    # Select from newest to oldest
    selected_pairs: list[tuple[dict, dict]] = []
    total_tokens = 0

    for pair in reversed(pairs):
        pair_tokens = pair[0]["token_count"] + pair[1]["token_count"]
        if total_tokens + pair_tokens > available_tokens:
            break
        selected_pairs.append(pair)
        total_tokens += pair_tokens

    # Reverse back to chronological order
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
