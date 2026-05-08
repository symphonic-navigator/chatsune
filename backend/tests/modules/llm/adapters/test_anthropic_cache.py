"""Unit tests for the Anthropic cache strategy library."""
from __future__ import annotations

import pytest

from backend.modules.llm._adapters._anthropic_cache import is_anthropic_model


@pytest.mark.parametrize("model_id", [
    "anthropic/claude-3-7-sonnet-20250219",
    "~anthropic/claude-opus-4-1",
    "claude-haiku-4-5",
    "claude-3-7-sonnet-20250219",
    "anthropic/claude-3.5-sonnet-vision",
    "ANTHROPIC/Claude-Sonnet-4-5",
])
def test_is_anthropic_model_positive(model_id: str) -> None:
    assert is_anthropic_model(model_id)


@pytest.mark.parametrize("model_id", [
    "openai/gpt-4",
    "openai/gpt-4o",
    "meta/llama-3.3-70b",
    "mistral-large-latest",
    "anthropic/claude-instant-1",
    "meta/llama-claude-skin",
    "",
    "anthropic/",
    "claude",
    "claude-haiku/",          # trailing slash — tail is empty; must NOT match
    "anthropic/claude-haiku/", # trailing slash with prefix — same; must NOT match
])
def test_is_anthropic_model_negative(model_id: str) -> None:
    assert not is_anthropic_model(model_id)


from backend.modules.llm._adapters._anthropic_cache import (
    BLOCK_SIZE,
    CacheMarker,
    compute_cache_markers,
)
from shared.dtos.inference import CompletionMessage, ContentPart


def _msg(role: str, text: str = "x") -> CompletionMessage:
    return CompletionMessage(
        role=role, content=[ContentPart(type="text", text=text)],
    )


def test_compute_markers_off_returns_empty() -> None:
    msgs = [_msg("system"), _msg("user")]
    assert compute_cache_markers(msgs, "off") == []


def test_compute_markers_empty_messages_returns_empty() -> None:
    assert compute_cache_markers([], "5m") == []


def test_compute_markers_single_user_message() -> None:
    # Only one user message — no system, no tail (len < 2 after the
    # tail check since tail_index would be -1).
    msgs = [_msg("user")]
    assert compute_cache_markers(msgs, "5m") == []


def test_compute_markers_system_only_with_one_user() -> None:
    # System + one user message: system marker, no tail (tail would
    # collide with system at index 0).
    msgs = [_msg("system"), _msg("user")]
    result = compute_cache_markers(msgs, "5m")
    assert result == [CacheMarker(message_index=0, ttl="1h")]


def test_compute_markers_5m_short_conversation() -> None:
    # 5 messages, ttl=5m → System + Tail (no block, n < BLOCK_SIZE)
    msgs = [_msg("system")] + [_msg("user"), _msg("assistant")] * 2
    assert len(msgs) == 5
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=3, ttl="5m"),
    ]


def test_compute_markers_5m_long_conversation_has_block() -> None:
    # 22 messages, ttl=5m → System + Block@15 (1h) + Tail@20 (5m).
    # last_block_end = (22 // 8) * 8 - 1 = 15.
    msgs = [_msg("system")] + [_msg("user")] * 21
    assert len(msgs) == 22
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=15, ttl="1h"),
        CacheMarker(message_index=20, ttl="5m"),
    ]


def test_compute_markers_1h_long_conversation_tail_is_1h() -> None:
    # Same shape as above but ttl=1h → tail switches to 1h.
    msgs = [_msg("system")] + [_msg("user")] * 21
    result = compute_cache_markers(msgs, "1h")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=15, ttl="1h"),
        CacheMarker(message_index=20, ttl="1h"),
    ]


def test_compute_markers_block_collides_with_tail_dedupes() -> None:
    # 9 messages: tail_index = 7, last_block_end = 7. Block placed,
    # tail dedupes (no double marker at index 7).
    msgs = [_msg("system")] + [_msg("user")] * 8
    assert len(msgs) == 9
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=7, ttl="1h"),
    ]


def test_compute_markers_block_at_end_minus_one_is_skipped() -> None:
    # 8 messages: last_block_end = 7, tail_index = 6. Block check
    # requires last_block_end < n - 1 (i.e. < 7), so block is NOT
    # placed. Result: System + Tail@6.
    msgs = [_msg("system")] + [_msg("user")] * 7
    assert len(msgs) == 8
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=6, ttl="5m"),
    ]


def test_compute_markers_no_system_message() -> None:
    # First message is user, not system → no system marker.
    # 22 user/assistant messages. last_block_end = 15.
    msgs = [_msg("user")] * 22
    result = compute_cache_markers(msgs, "1h")
    assert result == [
        CacheMarker(message_index=15, ttl="1h"),
        CacheMarker(message_index=20, ttl="1h"),
    ]


def test_block_size_is_eight() -> None:
    assert BLOCK_SIZE == 8
