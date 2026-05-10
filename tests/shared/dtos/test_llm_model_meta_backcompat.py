"""Backwards-compatibility tests for ``shared/dtos/llm.ModelMetaDto``.

Cached ``ModelMetaDto`` JSON blobs written before the capabilities migration
do not carry ``reasoning`` or ``tools`` keys. Production keeps these blobs in
Redis with a 30-minute TTL, which means the deserialiser MUST tolerate their
absence — see CLAUDE.md §Data-Model Migrations.
"""

from shared.dtos.llm import ModelMetaDto


def _legacy_payload() -> dict:
    """An old-shape cached document — no ``reasoning``, no ``tools``."""
    return {
        "connection_id": "conn-1",
        "connection_slug": "ollama",
        "connection_display_name": "Ollama",
        "model_id": "llama3.2",
        "display_name": "llama3.2",
        "context_window": 8192,
        "supports_vision": False,
        "supports_tool_calls": False,
    }


def test_model_meta_dto_validates_legacy_payload_without_reasoning_or_tools():
    dto = ModelMetaDto.model_validate(_legacy_payload())
    assert dto.reasoning.kind == "no_reasoning"
    assert dto.tools.supported is False
    assert dto.supports_reasoning is False


def test_model_meta_dto_legacy_payload_preserves_other_fields():
    dto = ModelMetaDto.model_validate(_legacy_payload())
    assert dto.connection_id == "conn-1"
    assert dto.model_id == "llama3.2"
    assert dto.context_window == 8192
    # The legacy bool field on the document still wins for callers that read it.
    assert dto.supports_tool_calls is False


def test_model_meta_dto_explicit_reasoning_and_tools_still_honoured():
    payload = _legacy_payload() | {
        "reasoning": {"kind": "optional", "default_on": True},
        "tools": {"supported": True, "exclusive_with_reasoning": False},
        "supports_tool_calls": True,
    }
    dto = ModelMetaDto.model_validate(payload)
    assert dto.reasoning.kind == "optional"
    assert dto.tools.supported is True
    assert dto.supports_reasoning is True
