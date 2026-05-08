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
])
def test_is_anthropic_model_negative(model_id: str) -> None:
    assert not is_anthropic_model(model_id)
