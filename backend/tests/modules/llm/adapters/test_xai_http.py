"""Tests for the xAI HTTP adapter — identity, template, and config schema."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter


def _resolved_conn(api_key: str = "xai-test-key") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-xai-1",
        user_id="u1",
        adapter_type="xai_http",
        display_name="Chris's xAI",
        slug="chris-xai",
        config={
            "url": "https://api.x.ai/v1",
            "api_key": api_key,
            "max_parallel": 4,
        },
        created_at=now,
        updated_at=now,
    )


def test_adapter_identity():
    assert XaiHttpAdapter.adapter_type == "xai_http"
    assert XaiHttpAdapter.display_name == "xAI / Grok"
    assert XaiHttpAdapter.view_id == "xai_http"
    assert "api_key" in XaiHttpAdapter.secret_fields


def test_single_template_for_xai_cloud():
    tmpls = XaiHttpAdapter.templates()
    assert len(tmpls) == 1
    t = tmpls[0]
    assert t.id == "xai_cloud"
    assert t.config_defaults["url"] == "https://api.x.ai/v1"
    assert t.config_defaults["max_parallel"] == 4
    assert t.required_config_fields == ("api_key",)


def test_config_schema_lists_url_api_key_max_parallel():
    schema = XaiHttpAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"url", "api_key", "max_parallel"}


import pytest


@pytest.mark.asyncio
async def test_fetch_models_returns_one_grok_4_1_fast():
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_resolved_conn())
    assert len(metas) == 1
    m = metas[0]
    assert m.model_id == "grok-4.1-fast"
    assert m.display_name == "Grok 4.1 Fast"
    assert m.context_window == 200_000
    assert m.supports_reasoning is True
    assert m.supports_vision is True
    assert m.supports_tool_calls is True
    assert m.connection_id == "conn-xai-1"
    assert m.connection_slug == "chris-xai"


from shared.dtos.inference import CompletionMessage, ContentPart, ToolCallResult
from backend.modules.llm._adapters._xai_http import _translate_message


def test_translate_text_only_user_message():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hello")],
    )
    result = _translate_message(msg)
    assert result == {"role": "user", "content": "hello"}


def test_translate_image_message_uses_openai_image_url_format():
    msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="what is this?"),
            ContentPart(type="image", data="AAA=", media_type="image/png"),
        ],
    )
    result = _translate_message(msg)
    assert result["role"] == "user"
    assert isinstance(result["content"], list)
    assert result["content"][0] == {"type": "text", "text": "what is this?"}
    img = result["content"][1]
    assert img["type"] == "image_url"
    assert img["image_url"]["url"] == "data:image/png;base64,AAA="


def test_translate_assistant_with_tool_calls():
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="looking that up")],
        tool_calls=[
            ToolCallResult(id="call_a", name="web_search",
                           arguments='{"query":"grok"}'),
        ],
    )
    result = _translate_message(msg)
    assert result["role"] == "assistant"
    assert result["content"] == "looking that up"
    assert result["tool_calls"] == [
        {
            "id": "call_a",
            "type": "function",
            "function": {"name": "web_search", "arguments": '{"query":"grok"}'},
        },
    ]


def test_translate_tool_role_message():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"results":[]}')],
        tool_call_id="call_a",
    )
    result = _translate_message(msg)
    assert result == {
        "role": "tool",
        "content": '{"results":[]}',
        "tool_call_id": "call_a",
    }
