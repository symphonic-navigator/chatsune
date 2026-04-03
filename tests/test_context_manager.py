import pytest
from backend.modules.chat._context import (
    calculate_budget,
    select_message_pairs,
    get_ampel_status,
    ContextBudget,
)


def test_calculate_budget():
    budget = calculate_budget(
        max_context_tokens=8192,
        system_prompt_tokens=200,
        new_message_tokens=50,
    )
    # safety = floor(8192 * 0.165) = 1351
    # response_reserve = 1000 + 50 = 1050
    # available = 8192 - 1351 - 200 - 1050 = 5591
    assert budget.available_for_chat == 5591
    assert budget.safety_reserve == 1351
    assert budget.response_reserve == 1050


def test_calculate_budget_negative_available_clamped_to_zero():
    budget = calculate_budget(
        max_context_tokens=2000,
        system_prompt_tokens=1500,
        new_message_tokens=500,
    )
    # safety = floor(2000 * 0.165) = 330
    # response_reserve = 1000 + 500 = 1500
    # available = 2000 - 330 - 1500 - 1500 = negative => 0
    assert budget.available_for_chat == 0


def test_select_message_pairs_all_fit():
    messages = [
        {"role": "user", "content": "hi", "token_count": 10},
        {"role": "assistant", "content": "hello", "token_count": 15},
        {"role": "user", "content": "bye", "token_count": 10},
        {"role": "assistant", "content": "cya", "token_count": 10},
    ]
    selected, total_tokens = select_message_pairs(messages, available_tokens=1000)
    assert len(selected) == 4
    assert total_tokens == 45


def test_select_message_pairs_budget_exceeded():
    messages = [
        {"role": "user", "content": "old", "token_count": 100},
        {"role": "assistant", "content": "old reply", "token_count": 100},
        {"role": "user", "content": "new", "token_count": 50},
        {"role": "assistant", "content": "new reply", "token_count": 50},
    ]
    # Budget only fits the newest pair
    selected, total_tokens = select_message_pairs(messages, available_tokens=150)
    assert len(selected) == 2
    assert selected[0]["content"] == "new"
    assert selected[1]["content"] == "new reply"
    assert total_tokens == 100


def test_select_message_pairs_empty():
    selected, total_tokens = select_message_pairs([], available_tokens=1000)
    assert selected == []
    assert total_tokens == 0


def test_select_message_pairs_single_user_message_no_pair():
    messages = [
        {"role": "user", "content": "hi", "token_count": 10},
    ]
    # Incomplete trailing pair — no complete pairs to select
    selected, total_tokens = select_message_pairs(messages, available_tokens=1000)
    assert selected == []
    assert total_tokens == 0


def test_get_ampel_green():
    assert get_ampel_status(0.3) == "green"
    assert get_ampel_status(0.0) == "green"
    assert get_ampel_status(0.49) == "green"


def test_get_ampel_yellow():
    assert get_ampel_status(0.5) == "yellow"
    assert get_ampel_status(0.64) == "yellow"


def test_get_ampel_orange():
    assert get_ampel_status(0.65) == "orange"
    assert get_ampel_status(0.79) == "orange"


def test_get_ampel_red():
    assert get_ampel_status(0.8) == "red"
    assert get_ampel_status(0.95) == "red"
    assert get_ampel_status(1.0) == "red"
