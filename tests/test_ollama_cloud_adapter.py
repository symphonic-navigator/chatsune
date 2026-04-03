import httpx
import pytest
import respx

from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter


@pytest.fixture
def adapter() -> OllamaCloudAdapter:
    return OllamaCloudAdapter(base_url="https://test.ollama.com")


@respx.mock
async def test_validate_key_returns_true_on_200(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/me").mock(
        return_value=httpx.Response(200, json={"username": "testuser"})
    )
    result = await adapter.validate_key("valid-key")
    assert result is True


@respx.mock
async def test_validate_key_returns_false_on_401(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/me").mock(
        return_value=httpx.Response(401)
    )
    result = await adapter.validate_key("invalid-key")
    assert result is False


@respx.mock
async def test_validate_key_returns_false_on_403(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/me").mock(
        return_value=httpx.Response(403)
    )
    result = await adapter.validate_key("forbidden-key")
    assert result is False


@respx.mock
async def test_fetch_models_returns_models_with_capabilities(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "mistral-large-3:675b"},
            ]
        })
    )
    respx.post("https://test.ollama.com/api/show").mock(
        return_value=httpx.Response(200, json={
            "details": {
                "parameter_size": "675000000000",
                "quantization_level": "FP8",
            },
            "model_info": {
                "general.architecture": "mistral3",
                "general.parameter_count": 675000000000,
                "mistral3.context_length": 262144,
            },
            "capabilities": ["completion", "tools", "vision"],
        })
    )

    models = await adapter.fetch_models()
    assert len(models) == 1

    m = models[0]
    assert m.provider_id == "ollama_cloud"
    assert m.model_id == "mistral-large-3:675b"
    assert m.display_name == "Mistral Large 3 (675B)"
    assert m.context_window == 262144
    assert m.supports_tool_calls is True
    assert m.supports_vision is True
    assert m.supports_reasoning is False
    assert m.parameter_count == "675B"
    assert m.quantisation_level == "FP8"


@respx.mock
async def test_fetch_models_handles_missing_details(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [{"name": "phi3"}]
        })
    )
    respx.post("https://test.ollama.com/api/show").mock(
        return_value=httpx.Response(200, json={
            "model_info": {
                "phi3.context_length": 4096,
            },
            "capabilities": ["completion"],
        })
    )

    models = await adapter.fetch_models()
    assert len(models) == 1

    m = models[0]
    assert m.parameter_count is None
    assert m.quantisation_level is None
    assert m.context_window == 4096
    assert m.supports_tool_calls is False
    assert m.supports_vision is False


@respx.mock
async def test_fetch_models_skips_model_on_show_failure(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "good-model"},
                {"name": "broken-model"},
            ]
        })
    )
    respx.post(
        "https://test.ollama.com/api/show",
    ).mock(side_effect=[
        httpx.Response(200, json={
            "model_info": {"arch.context_length": 8192},
            "capabilities": ["completion"],
        }),
        httpx.Response(500),
    ])

    models = await adapter.fetch_models()
    assert len(models) == 1
    assert models[0].model_id == "good-model"


def test_format_parameter_count():
    from backend.modules.llm._adapters._ollama_cloud import _format_parameter_count

    assert _format_parameter_count(675_000_000_000) == "675B"
    assert _format_parameter_count(7_000_000_000) == "7B"
    assert _format_parameter_count(7_500_000_000) == "7.5B"
    assert _format_parameter_count(70_000_000_000) == "70B"
    assert _format_parameter_count(1_500_000_000_000) == "1.5T"
    assert _format_parameter_count(405_000_000) == "405M"
    assert _format_parameter_count(0) is None
    assert _format_parameter_count(None) is None
