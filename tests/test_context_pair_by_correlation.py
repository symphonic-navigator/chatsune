"""Unit tests for ``select_message_pairs`` after the correlation_id rewrite.

See ``devdocs/specs/2026-05-17-pair-by-correlation-design.md`` §7.1.
These tests cover the behaviour the new algorithm is supposed to
deliver — they are the regression suite for bugs a-2 (orphan user
swept silently), a-3 (two-tab race poisons history) and a-10
(aborted user pollutes downstream context).
"""
from __future__ import annotations

from backend.modules.chat._context import select_message_pairs


def _u(cid: str, *, content: str = "u", tokens: int = 10) -> dict:
    return {
        "role": "user",
        "content": content,
        "token_count": tokens,
        "correlation_id": cid,
        "status": "completed",
    }


def _a(cid: str, *, content: str = "a", tokens: int = 10,
       status: str = "completed") -> dict:
    return {
        "role": "assistant",
        "content": content,
        "token_count": tokens,
        "correlation_id": cid,
        "status": status,
    }


def test_basic_pairing_three_turns():
    """All three completed pairs are returned in chronological order."""
    msgs = [
        _u("A", content="u-A"), _a("A", content="a-A"),
        _u("B", content="u-B"), _a("B", content="a-B"),
        _u("C", content="u-C"), _a("C", content="a-C"),
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == [
        "u-A", "a-A", "u-B", "a-B", "u-C", "a-C",
    ]
    assert total == 60


def test_aborted_assistant_drops_pair():
    """Aborted-assistant pair is dropped; sibling user goes with it."""
    msgs = [
        _u("A", content="u-A"), _a("A", content="a-A", status="aborted"),
        _u("B", content="u-B"), _a("B", content="a-B"),
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == ["u-B", "a-B"]
    assert total == 20


def test_refused_assistant_drops_pair():
    """Refused-assistant pair is dropped (same logic as aborted)."""
    msgs = [
        _u("A", content="u-A"), _a("A", content="a-A", status="refused"),
        _u("B", content="u-B"), _a("B", content="a-B"),
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == ["u-B", "a-B"]
    assert total == 20


def test_orphan_user_dropped():
    """User message with no matching assistant cid is dropped silently."""
    msgs = [
        _u("A", content="u-A"), _a("A", content="a-A"),
        _u("B", content="u-B"),  # orphan — no assistant for cid B
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == ["u-A", "a-A"]
    assert total == 20


def test_two_tab_race_regression():
    """Two-tab race: ``user_A → user_B → aborted-asst(cid=A) → completed-asst(cid=B)``.

    Position-based pairing would mismatch user_A with aborted-asst and
    user_B with completed-asst-for-B. Worse, the old code also paired
    user_B with assistant-for-A under different write orders. The new
    correlation-id pair-builder must:

    - Pair user_A with the aborted assistant; drop the pair.
    - Pair user_B with the completed assistant; keep the pair.

    Expected output: ``[user_B, completed-asst-for-B]``.
    """
    msgs = [
        _u("A", content="u-A"),
        _u("B", content="u-B"),
        _a("A", content="a-A-aborted", status="aborted"),
        _a("B", content="a-B"),
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == ["u-B", "a-B"]
    assert total == 20


def test_missing_correlation_id_defensive_skip():
    """Doc without ``correlation_id`` is skipped without crashing."""
    msgs = [
        {"role": "user", "content": "no-cid", "token_count": 10,
         "status": "completed"},
        {"role": "assistant", "content": "no-cid-reply", "token_count": 10,
         "status": "completed"},
        _u("B", content="u-B"), _a("B", content="a-B"),
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == ["u-B", "a-B"]
    assert total == 20


def test_budget_cap_drops_oldest_pair():
    """Newest-first budget selection — oldest pair dropped when over budget."""
    msgs = [
        _u("A", content="u-A", tokens=100), _a("A", content="a-A", tokens=100),
        _u("B", content="u-B", tokens=50),  _a("B", content="a-B", tokens=50),
        _u("C", content="u-C", tokens=50),  _a("C", content="a-C", tokens=50),
    ]
    # Fits only the latest two pairs (200 tokens of 200 budget).
    selected, total = select_message_pairs(msgs, available_tokens=200)
    assert [m["content"] for m in selected] == ["u-B", "a-B", "u-C", "a-C"]
    assert total == 200


def test_regenerate_overwrite_slot_last_write_wins():
    """Two assistants sharing the same cid (regenerate replaced earlier
    one): last-write-wins on the slot, pair uses the latest assistant.
    """
    msgs = [
        _u("A", content="u-A"),
        _a("A", content="a-A-old"),
        _a("A", content="a-A-new"),  # regenerate result
    ]
    selected, total = select_message_pairs(msgs, available_tokens=1000)
    assert [m["content"] for m in selected] == ["u-A", "a-A-new"]
    assert total == 20
