"""Regression tests for parse_model_unique_id — unique_id format is
<connection_slug>:<model_slug> where the left segment is a user-defined slug."""

import pytest

from backend.modules.llm import LlmInvalidModelUniqueIdError, parse_model_unique_id


def test_parse_splits_on_first_colon():
    slug, model = parse_model_unique_id("ollama-cloud:llama3.3:70b")
    assert slug == "ollama-cloud"
    assert model == "llama3.3:70b"


def test_parse_simple_model():
    slug, model = parse_model_unique_id("my-connection:llama3.2")
    assert slug == "my-connection"
    assert model == "llama3.2"


def test_parse_rejects_missing_colon():
    with pytest.raises(LlmInvalidModelUniqueIdError):
        parse_model_unique_id("no-colon-here")


def test_parse_rejects_empty_left_segment():
    with pytest.raises(LlmInvalidModelUniqueIdError):
        parse_model_unique_id(":model-without-slug")


def test_parse_rejects_empty_right_segment():
    with pytest.raises(LlmInvalidModelUniqueIdError):
        parse_model_unique_id("slug-without-model:")
