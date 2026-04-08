"""Tests for the conservative token-length helper."""

from backend.modules.llm import _token_estimate
from backend.modules.llm._token_estimate import (
    context_window_for,
    estimate_tokens,
)


def test_estimate_tokens_empty() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_short_string_rounds_up_to_one() -> None:
    assert estimate_tokens("abc") == 1


def test_estimate_tokens_scales_linearly() -> None:
    assert estimate_tokens("a" * 30) == 10


def test_context_window_unknown_returns_default() -> None:
    assert context_window_for("no_such_provider", "no_such_model") == 8192


def test_context_window_specific_override(monkeypatch) -> None:
    monkeypatch.setitem(
        _token_estimate._CONTEXT_WINDOWS, "ollama_cloud:llama3.2", 16384,
    )
    assert context_window_for("ollama_cloud", "llama3.2") == 16384


def test_context_window_slug_only_fallback(monkeypatch) -> None:
    monkeypatch.setitem(_token_estimate._CONTEXT_WINDOWS, "llama3.2", 32768)
    assert context_window_for("some_other_provider", "llama3.2") == 32768
