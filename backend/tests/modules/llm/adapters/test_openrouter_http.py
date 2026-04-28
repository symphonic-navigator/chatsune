"""Tests for the OpenRouter HTTP adapter.

Coverage grows task by task; this initial pass exercises adapter
identity and premium-only registration. Later tasks add model-list
mapping, defensive modality filter, auth/error handling, payload
shape (incl. reasoning logic), SSE parser extensions, and the /test
sub-router.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from backend.modules.llm._adapters._openrouter_http import (
    OpenRouterHttpAdapter,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    get_adapter_class,
)


def test_adapter_identity():
    a = OpenRouterHttpAdapter()
    assert a.adapter_type == "openrouter_http"
    assert a.display_name == "OpenRouter"
    assert a.view_id == "openrouter_http"
    assert a.secret_fields == frozenset({"api_key"})


def test_adapter_is_premium_only_not_user_creatable():
    # User-facing registry must NOT contain openrouter — it is premium-only.
    assert "openrouter_http" not in ADAPTER_REGISTRY
    # But the resolver helper should find it.
    assert get_adapter_class("openrouter_http") is OpenRouterHttpAdapter


def _resolved() -> ResolvedConnection:
    return ResolvedConnection(
        id="premium:openrouter",
        user_id="u1",
        adapter_type="openrouter_http",
        display_name="OpenRouter",
        slug="openrouter",
        config={
            "url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-v1-fake",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


_MODELS_USER_RESPONSE = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128_000,
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            "top_provider": {
                "context_length": 128_000,
                "max_completion_tokens": 16_384,
                "is_moderated": True,
            },
            "supported_parameters": [
                "max_tokens", "temperature", "tools", "tool_choice",
            ],
            "expiration_date": None,
        },
        {
            "id": "deepseek/deepseek-r1:free",
            "name": "DeepSeek: R1 (free)",
            "context_length": 64_000,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {
                "context_length": 64_000,
                "max_completion_tokens": 8_192,
                "is_moderated": False,
            },
            "supported_parameters": [
                "include_reasoning", "reasoning", "max_tokens", "temperature",
            ],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that returns a canned response."""

    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(_MODELS_USER_RESPONSE).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_maps_fields_correctly():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient,
    ):
        models = await a.fetch_models(_resolved())

    by_id = {m.model_id: m for m in models}

    gpt = by_id["openai/gpt-4o"]
    assert gpt.display_name == "OpenAI: GPT-4o"
    assert gpt.context_window == 128_000
    assert gpt.supports_vision is True       # input_modalities contains "image"
    assert gpt.supports_reasoning is False   # neither key in supported_parameters
    assert gpt.supports_tool_calls is True   # "tools" in supported_parameters
    assert gpt.is_moderated is True
    assert gpt.is_deprecated is False
    assert gpt.billing_category == "pay_per_token"
    assert gpt.connection_slug == "openrouter"

    r1 = by_id["deepseek/deepseek-r1:free"]
    assert r1.supports_vision is False
    assert r1.supports_reasoning is True     # both reasoning keys present
    assert r1.supports_tool_calls is False   # "tools" missing
    assert r1.is_moderated is False
    assert r1.billing_category == "free"     # both pricing fields == "0"


_MODELS_USER_RESPONSE_WITH_IMAGE_OUTPUT = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128_000,
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "stability/sdxl",
            "name": "SDXL",
            "context_length": 2048,
            "architecture": {
                "modality": "text->image",
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "multimodal/text-and-image-output",
            "name": "Mixed Output",
            "context_length": 32_000,
            "architecture": {
                "modality": "text->text+image",
                "input_modalities": ["text"],
                "output_modalities": ["text", "image"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "broken/missing-arch",
            "name": "No Architecture",
            "context_length": 1024,
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClientImageOutput(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(
                _MODELS_USER_RESPONSE_WITH_IMAGE_OUTPUT
            ).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_filters_non_text_output():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClientImageOutput,
    ):
        models = await a.fetch_models(_resolved())

    ids = {m.model_id for m in models}
    # Only the strict text-only output model survives.
    assert ids == {"openai/gpt-4o"}
