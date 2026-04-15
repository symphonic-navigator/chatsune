import pytest

from backend.modules.llm._adapters._ollama_http import _filter_unusable, _map_to_dto
from shared.dtos.llm import ModelMetaDto


def test_filter_unusable_drops_zero_context():
    a = ModelMetaDto(
        connection_id="conn-id",
        connection_display_name="Conn",
        model_id="llama3.3",
        display_name="Llama 3.3",
        context_window=131072,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
    )
    b = ModelMetaDto(
        connection_id="conn-id",
        connection_display_name="Conn",
        model_id="orphan-model",
        display_name="Orphan Model",
        context_window=0,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
    )
    result = _filter_unusable([a, b])
    assert result == [a]


def test_map_to_dto_propagates_quantisation_level():
    dto = _map_to_dto(
        "conn-id",
        "Conn",
        "my-conn-slug",
        "llama3.3",
        {
            "capabilities": [],
            "model_info": {"llama.context_length": 131072},
            "details": {"quantization_level": "Q4_K_M"},
        },
    )
    assert dto.quantisation_level == "Q4_K_M"
    assert dto.context_window == 131072
    assert dto.connection_slug == "my-conn-slug"
    assert dto.unique_id == "my-conn-slug:llama3.3"
