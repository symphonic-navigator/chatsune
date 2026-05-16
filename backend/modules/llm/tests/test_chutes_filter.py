"""Unit tests for the chutes_http catalogue filter and entry mapping."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.modules.llm._adapters._chutes_http import (
    ChutesHttpAdapter,
    _entry_to_meta,
)
from backend.modules.llm._adapters._types import ResolvedConnection


def _conn() -> ResolvedConnection:
    return ResolvedConnection(
        id="conn-1",
        user_id="user-1",
        adapter_type="chutes_http",
        display_name="My Chutes",
        slug="chutes-byok",
        config={"api_key": "cpk_test"},
        created_at=datetime(2026, 5, 16),
        updated_at=datetime(2026, 5, 16),
    )


def _entry(**overrides: object) -> dict:
    base: dict = {
        "id": "deepseek-ai/DeepSeek-V3.2-TEE",
        "context_length": 131_072,
        "max_output_length": 8192,
        "confidential_compute": True,
        "output_modalities": ["text"],
        "input_modalities": ["text"],
        "supported_features": ["tools", "json_mode"],
        "supported_sampling_parameters": ["temperature", "top_p"],
        "pricing": {"prompt": "0.28", "completion": "0.42"},
    }
    base.update(overrides)
    return base


def test_tee_false_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(_entry(confidential_compute=False), _conn(), adapter=adapter) is None


def test_tee_missing_is_dropped():
    adapter = ChutesHttpAdapter()
    e = _entry()
    del e["confidential_compute"]
    assert _entry_to_meta(e, _conn(), adapter=adapter) is None


def test_below_context_floor_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(_entry(context_length=32_000), _conn(), adapter=adapter) is None


def test_at_context_floor_is_kept():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(_entry(context_length=80_000), _conn(), adapter=adapter)
    assert meta is not None
    assert meta.context_window == 80_000


def test_image_only_output_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(_entry(output_modalities=["image"]), _conn(), adapter=adapter) is None


def test_mixed_output_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(
        _entry(output_modalities=["text", "image"]), _conn(), adapter=adapter,
    ) is None


def test_missing_output_modalities_is_dropped():
    adapter = ChutesHttpAdapter()
    e = _entry()
    del e["output_modalities"]
    assert _entry_to_meta(e, _conn(), adapter=adapter) is None


def test_valid_entry_maps_to_meta():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(_entry(), _conn(), adapter=adapter)
    assert meta is not None
    assert meta.model_id == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert meta.display_name == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert meta.context_window == 131_072
    assert meta.connection_id == "conn-1"
    assert meta.connection_slug == "chutes-byok"
    assert meta.connection_display_name == "My Chutes"
    assert meta.supports_tool_calls is True
    assert meta.supports_vision is False
    assert meta.billing_category == "pay_per_token"


def test_vision_model_sets_supports_vision():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(
        _entry(input_modalities=["text", "image"]), _conn(), adapter=adapter,
    )
    assert meta is not None
    assert meta.supports_vision is True


def test_free_model_billing_category():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(
        _entry(pricing={"prompt": "0", "completion": "0"}), _conn(), adapter=adapter,
    )
    assert meta is not None
    assert meta.billing_category == "free"


def test_features_and_sampling_params_stashed_on_adapter():
    adapter = ChutesHttpAdapter()
    _entry_to_meta(_entry(), _conn(), adapter=adapter)
    assert adapter._features_by_model_id["deepseek-ai/DeepSeek-V3.2-TEE"] == [
        "tools", "json_mode",
    ]
    assert adapter._sampling_params_by_model_id["deepseek-ai/DeepSeek-V3.2-TEE"] == [
        "temperature", "top_p",
    ]


def test_reasoning_feature_yields_optional_reasoning():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(
        _entry(
            id="deepseek-ai/DeepSeek-R1-0528-TEE",
            supported_features=["tools", "reasoning"],
        ),
        _conn(), adapter=adapter,
    )
    assert meta is not None
    assert meta.reasoning.kind == "optional"


def test_no_reasoning_feature_yields_no_reasoning():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(_entry(), _conn(), adapter=adapter)  # default features = [tools, json_mode]
    assert meta is not None
    assert meta.reasoning.kind == "no_reasoning"
