"""Tests for the OpenRouter HTTP adapter.

Coverage grows task by task; this initial pass exercises adapter
identity and premium-only registration. Later tasks add model-list
mapping, defensive modality filter, auth/error handling, payload
shape (incl. reasoning logic), SSE parser extensions, and the /test
sub-router.
"""

from __future__ import annotations

from backend.modules.llm._adapters._openrouter_http import (
    OpenRouterHttpAdapter,
)
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
