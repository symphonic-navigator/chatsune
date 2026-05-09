from unittest.mock import patch

from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability


def _make_model(connection_slug: str, model_id: str, context_window: int) -> ModelMetaDto:
    return ModelMetaDto(
        connection_id=f"{connection_slug}-conn-id",
        connection_slug=connection_slug,
        connection_display_name=connection_slug,
        model_id=model_id,
        display_name=model_id,
        context_window=context_window,
        reasoning=ReasoningCapability(kind="no_reasoning"),
        tools=ToolCapability(supported=False),
        supports_vision=False,
        supports_tool_calls=False,
    )


async def test_get_model_context_window_found():
    model = _make_model("ollama_cloud", "llama3.2", 131072)

    async def _stub_metadata(user_id, model_unique_id):
        if model_unique_id == "ollama_cloud:llama3.2":
            return model
        return None

    with patch("backend.modules.llm.get_model_metadata", side_effect=_stub_metadata):
        from backend.modules.llm import get_model_context_window
        result = await get_model_context_window("user-1", "ollama_cloud:llama3.2")
        assert result == 131072


async def test_get_model_context_window_not_found():
    async def _stub_metadata(user_id, model_unique_id):
        return None

    with patch("backend.modules.llm.get_model_metadata", side_effect=_stub_metadata):
        from backend.modules.llm import get_model_context_window
        result = await get_model_context_window("user-1", "ollama_cloud:nonexistent")
        assert result is None
