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


from backend.modules.chat._compaction import (
    determine_tail_start_index,
    sanitise_source,
    select_source_range,
)


def test_select_source_range_no_prev_checkpoint():
    msgs = _msgs(20, tokens_per=10)
    source, tail = select_source_range(msgs, tail_start_index=15, prev_tail_start_id=None)
    assert len(source) == 15
    assert source[-1]["_id"] == "m-14"
    assert len(tail) == 5


def test_select_source_range_with_prev_checkpoint():
    msgs = _msgs(20, tokens_per=10)
    source, tail = select_source_range(
        msgs, tail_start_index=15, prev_tail_start_id="m-5",
    )
    assert [m["_id"] for m in source] == [f"m-{i}" for i in range(5, 15)]


def test_sanitise_source_drops_tool_roles_and_tool_call_assistants():
    msgs = [
        {"_id": "m-1", "role": "user", "content": "hi", "token_count": 2},
        {"_id": "m-2", "role": "assistant", "content": "hello", "token_count": 2},
        {"_id": "m-3", "role": "tool", "content": "{}", "token_count": 1},
        {"_id": "m-4", "role": "assistant", "content": "", "token_count": 0},
        {"_id": "m-5", "role": "assistant", "content": "back to text", "token_count": 3},
    ]
    cleaned = sanitise_source(msgs)
    assert [m["_id"] for m in cleaned] == ["m-1", "m-2", "m-5"]
