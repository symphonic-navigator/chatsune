"""Tests for the Novita AI HTTP adapter.

Mirrors `test_openrouter_http.py`; coverage grows task by task.
"""

from __future__ import annotations

from backend.modules.llm._adapters._novita_http import NovitaHttpAdapter
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    _PREMIUM_ONLY_ADAPTERS,
    get_adapter_class,
)


def test_adapter_identity():
    a = NovitaHttpAdapter()
    assert a.adapter_type == "novita_http"
    assert a.display_name == "Novita AI"
    assert a.view_id == "novita_http"
    assert a.secret_fields == frozenset({"api_key"})


def test_adapter_is_premium_only_not_user_creatable():
    # User-facing registry must NOT contain novita — it is premium-only.
    assert "novita_http" not in ADAPTER_REGISTRY
    # But the resolver helper should find it.
    assert get_adapter_class("novita_http") is NovitaHttpAdapter


def test_adapter_registered_in_premium_only_map():
    assert "novita_http" in _PREMIUM_ONLY_ADAPTERS
    assert _PREMIUM_ONLY_ADAPTERS["novita_http"] is NovitaHttpAdapter
