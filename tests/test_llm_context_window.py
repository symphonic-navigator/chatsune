import pytest
from unittest.mock import AsyncMock, patch
from shared.dtos.llm import ModelMetaDto


def _make_model(provider_id: str, model_id: str, context_window: int) -> ModelMetaDto:
    return ModelMetaDto(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        context_window=context_window,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
    )


async def test_get_model_context_window_found():
    models = [
        _make_model("ollama_cloud", "llama3.2", 131072),
        _make_model("ollama_cloud", "mistral", 32768),
    ]

    with patch("backend.modules.llm.get_models", return_value=models), \
         patch("backend.modules.llm.get_db"), \
         patch("backend.modules.llm.get_redis"):
        from backend.modules.llm import get_model_context_window
        result = await get_model_context_window("ollama_cloud", "llama3.2")
        assert result == 131072


async def test_get_model_context_window_not_found():
    models = [_make_model("ollama_cloud", "mistral", 32768)]

    with patch("backend.modules.llm.get_models", return_value=models), \
         patch("backend.modules.llm.get_db"), \
         patch("backend.modules.llm.get_redis"):
        from backend.modules.llm import get_model_context_window
        result = await get_model_context_window("ollama_cloud", "nonexistent")
        assert result is None
