"""Tail determination: 6 turns OR 20% of model context, whichever is larger."""

from backend.modules.chat._compaction import determine_tail_start_index


def _msgs(n: int, tokens_per: int = 100) -> list[dict]:
    return [
        {"_id": f"m-{i}", "role": "user" if i % 2 == 0 else "assistant",
         "token_count": tokens_per}
        for i in range(n)
    ]


def test_short_session_returns_index_zero():
    msgs = _msgs(4)
    assert determine_tail_start_index(msgs, model_context=10_000) == 0


def test_long_session_uses_12_message_floor():
    msgs = _msgs(100, tokens_per=100)
    idx = determine_tail_start_index(msgs, model_context=200_000)
    assert idx == 0


def test_long_session_uses_token_budget_when_larger():
    msgs = _msgs(100, tokens_per=1000)
    idx = determine_tail_start_index(msgs, model_context=50_000)
    assert idx == 88


def test_long_session_uses_floor_token_rule_when_larger():
    msgs = _msgs(100, tokens_per=100)
    idx = determine_tail_start_index(msgs, model_context=100_000)
    assert idx == 0
