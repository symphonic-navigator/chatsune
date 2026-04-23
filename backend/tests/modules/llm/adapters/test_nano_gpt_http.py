"""Tests for the Nano-GPT HTTP adapter skeleton — identity, templates,
config schema, and the Phase-2 stub behaviour of ``stream_completion``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._types import ResolvedConnection


def _resolved_conn(
    *, base_url: str = "https://api.nano-gpt.com/v1",
    api_key: str = "nano-test-key",
) -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-nano-1",
        user_id="u1",
        adapter_type="nano_gpt_http",
        display_name="Chris's Nano-GPT",
        slug="chris-nano",
        config={
            "base_url": base_url,
            "api_key": api_key,
            "max_parallel": 3,
        },
        created_at=now,
        updated_at=now,
    )


def test_adapter_identity():
    assert NanoGptHttpAdapter.adapter_type == "nano_gpt_http"
    assert NanoGptHttpAdapter.display_name == "Nano-GPT"
    assert NanoGptHttpAdapter.view_id == "nano_gpt_http"
    assert NanoGptHttpAdapter.secret_fields == frozenset({"api_key"})


def test_templates_single_default():
    tpls = NanoGptHttpAdapter.templates()
    assert len(tpls) == 1
    tpl = tpls[0]
    assert tpl.id == "nano_gpt_default"
    assert tpl.display_name == "Nano-GPT"
    assert tpl.slug_prefix == "nano"
    assert tpl.config_defaults["base_url"] == "https://api.nano-gpt.com/v1"
    assert tpl.config_defaults["max_parallel"] == 3
    assert "api_key" in tpl.required_config_fields


def test_config_schema_has_expected_fields():
    schema = NanoGptHttpAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"base_url", "api_key", "max_parallel"}

    api_key_field = next(f for f in schema if f.name == "api_key")
    assert api_key_field.type == "secret"
    assert api_key_field.required is True

    base_url_field = next(f for f in schema if f.name == "base_url")
    assert base_url_field.type == "url"
    assert base_url_field.required is False

    max_parallel_field = next(f for f in schema if f.name == "max_parallel")
    assert max_parallel_field.type == "integer"
    assert max_parallel_field.min == 1
    assert max_parallel_field.max == 32


@pytest.mark.asyncio
async def test_fetch_models_is_not_implemented_stub():
    adapter = NanoGptHttpAdapter()
    with pytest.raises(NotImplementedError, match="Task 8"):
        await adapter.fetch_models(_resolved_conn())


@pytest.mark.asyncio
async def test_stream_completion_raises_phase_2_not_implemented():
    adapter = NanoGptHttpAdapter()
    conn = _resolved_conn()
    # stream_completion yields events — to trigger the raise we must
    # start iterating. The NotImplementedError is raised on the first
    # __anext__() call.
    agen = adapter.stream_completion(conn, request=None)  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError, match="Phase 2"):
        async for _ in agen:
            break
