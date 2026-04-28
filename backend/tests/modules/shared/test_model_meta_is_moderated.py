"""Schema test for the is_moderated field on ModelMetaDto."""

from shared.dtos.llm import ModelMetaDto


def _base() -> dict:
    return {
        "connection_id": "c1",
        "connection_slug": "openrouter",
        "connection_display_name": "OpenRouter",
        "model_id": "openai/gpt-4o",
        "display_name": "GPT-4o",
        "context_window": 128_000,
        "supports_reasoning": False,
        "supports_vision": True,
        "supports_tool_calls": True,
    }


def test_is_moderated_defaults_to_none():
    dto = ModelMetaDto(**_base())
    assert dto.is_moderated is None


def test_is_moderated_accepts_true():
    dto = ModelMetaDto(**_base(), is_moderated=True)
    assert dto.is_moderated is True


def test_is_moderated_accepts_false():
    dto = ModelMetaDto(**_base(), is_moderated=False)
    assert dto.is_moderated is False
