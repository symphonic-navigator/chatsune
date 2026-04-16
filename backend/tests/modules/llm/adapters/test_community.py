"""Tests for the Community adapter — consumer-side CSP bridge."""

from __future__ import annotations

import pytest

from backend.modules.llm._adapters._community import CommunityAdapter


def test_adapter_identity():
    assert CommunityAdapter.adapter_type == "community"
    assert CommunityAdapter.display_name == "Community"
    assert CommunityAdapter.view_id == "community"
    assert "api_key" in CommunityAdapter.secret_fields
    assert "homelab_id" not in CommunityAdapter.secret_fields


def test_adapter_has_one_template():
    tmpls = CommunityAdapter.templates()
    assert len(tmpls) == 1
    t = tmpls[0]
    assert t.required_config_fields == ("homelab_id", "api_key")


def test_adapter_config_schema_has_two_fields():
    schema = CommunityAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"homelab_id", "api_key"}
