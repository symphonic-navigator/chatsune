"""Tests for DeepSeekV4Driver — capability spec, request body, chunk parsing."""
from __future__ import annotations

import pytest

from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)


def test_deepseek_v4_capability_spec_for_openrouter():
    spec = deepseek_v4_capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")

    assert spec.first_class_support is True
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is not None
    assert spec.reasoning.effort.buckets == ["high", "max"]
    assert spec.reasoning.effort.default_bucket == "high"
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False


def test_deepseek_v4_capability_spec_is_router_agnostic_for_now():
    """Plan 1 ships only the OR builder; capability spec at this stage is
    identical regardless of (adapter_type, slug). Plans 2-4 may diverge it
    per router (e.g. Novita drops 'max' from effort buckets)."""
    or_spec = deepseek_v4_capability_spec(adapter_type="openrouter_http", slug="deepseek/deepseek-v4-pro")
    nano_spec = deepseek_v4_capability_spec(adapter_type="nano_gpt_http", slug="deepseek/deepseek-v4-pro:thinking")
    assert or_spec == nano_spec
