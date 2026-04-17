"""Tests for the Community adapter — consumer-side CSP bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.llm._adapters._community import CommunityAdapter
from backend.modules.llm._adapters._types import ResolvedConnection


def _resolved_conn(
    homelab_id: str = "Xk7bQ2eJn9m",
    api_key: str = "csapi_test_xyz",
) -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-1",
        user_id="u2",
        adapter_type="community",
        display_name="Alice's GPU",
        slug="alices-gpu",
        # Secrets are merged into config by the resolver — adapter reads them from there.
        config={"homelab_id": homelab_id, "api_key": api_key},
        created_at=now,
        updated_at=now,
    )


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


# ----- fetch_models -----


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_when_sidecar_offline(monkeypatch):
    from backend.modules.llm._adapters import _community

    monkeypatch.setattr(
        _community,
        "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: None),
    )
    # No homelab service call expected — sidecar offline short-circuits.
    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert out == []


@pytest.mark.asyncio
async def test_fetch_models_filters_by_allowlist(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_list_models = AsyncMock(
        return_value=[
            {
                "slug": "llama3.2:8b",
                "display_name": "Llama 3.2 8B",
                "context_length": 131072,
                "capabilities": ["chat"],
            },
            {
                "slug": "mistral:7b",
                "display_name": "Mistral 7B",
                "context_length": 32768,
                "capabilities": ["chat"],
            },
        ]
    )
    monkeypatch.setattr(
        _community,
        "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access_key = AsyncMock(
        return_value={"allowed_model_slugs": ["llama3.2:8b"]}
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert [m.model_id for m in out] == ["llama3.2:8b"]
    # Connection identity preserved on the DTO so the frontend can display it.
    assert out[0].connection_id == "conn-1"
    assert out[0].connection_slug == "alices-gpu"
    assert out[0].connection_display_name == "Alice's GPU"
    assert out[0].context_window == 131072


@pytest.mark.asyncio
async def test_fetch_models_empty_when_api_key_invalid(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_list_models = AsyncMock(return_value=[])
    monkeypatch.setattr(
        _community,
        "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access_key = AsyncMock(return_value=None)
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert out == []


@pytest.mark.asyncio
async def test_fetch_models_empty_when_config_missing(monkeypatch):
    from backend.modules.llm._adapters import _community

    # With no homelab_id we should never even reach the registry.
    sentinel = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(_community, "get_sidecar_registry", sentinel)

    now = datetime.now(UTC)
    empty = ResolvedConnection(
        id="conn-1",
        user_id="u2",
        adapter_type="community",
        display_name="",
        slug="",
        config={"homelab_id": "", "api_key": ""},
        created_at=now,
        updated_at=now,
    )
    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(empty)
    assert out == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_when_rpc_raises(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_list_models = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(
        _community,
        "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access_key = AsyncMock(
        return_value={"allowed_model_slugs": ["llama3.2:8b"]}
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_resolved_conn())
    assert out == []


# ----- stream_completion -----


def _completion_request(model_slug: str = "llama3.2:8b"):
    from shared.dtos.inference import (
        CompletionMessage,
        CompletionRequest,
        ContentPart,
    )

    return CompletionRequest(
        model=model_slug,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_stream_completion_translates_frames(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import (
        ContentDelta,
        StreamDone,
    )
    from backend.modules.llm._csp._frames import (
        StreamDelta,
        StreamEndFrame,
        StreamFrame,
    )

    frames = [
        StreamFrame(id="r", delta=StreamDelta(content="He")),
        StreamFrame(id="r", delta=StreamDelta(content="llo")),
        StreamEndFrame(
            id="r", finish_reason="stop",
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        ),
    ]

    async def gen():
        for f in frames:
            yield f

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_generate_chat = MagicMock(return_value=gen())

    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={
            "allowed_model_slugs": ["llama3.2:8b"],
            "api_key_id": "key-1",
            "max_concurrent": 1,
        }
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = []
    async for ev in adapter.stream_completion(_resolved_conn(), _completion_request()):
        events.append(ev)
    # Two content deltas + one terminal StreamDone.
    deltas = [e for e in events if isinstance(e, ContentDelta)]
    assert [d.delta for d in deltas] == ["He", "llo"]
    assert isinstance(events[-1], StreamDone)


@pytest.mark.asyncio
async def test_stream_completion_refused_when_model_not_allowed(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import StreamRefused

    fake_sidecar = MagicMock()
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(return_value=None)
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = [
        ev
        async for ev in adapter.stream_completion(
            _resolved_conn(), _completion_request("denied-model"),
        )
    ]
    assert len(events) == 1
    assert isinstance(events[0], StreamRefused)


@pytest.mark.asyncio
async def test_stream_completion_error_when_sidecar_offline(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import StreamError

    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: None),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={
            "allowed_model_slugs": ["llama3.2:8b"],
            "api_key_id": "key-1",
            "max_concurrent": 1,
        },
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = [
        ev
        async for ev in adapter.stream_completion(_resolved_conn(), _completion_request())
    ]
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "provider_unavailable"


@pytest.mark.asyncio
async def test_stream_completion_translates_thinking_delta(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import (
        ContentDelta,
        StreamDone,
        ThinkingDelta,
    )
    from backend.modules.llm._csp._frames import (
        StreamDelta,
        StreamEndFrame,
        StreamFrame,
    )

    frames = [
        StreamFrame(id="r", delta=StreamDelta(reasoning="thinking...")),
        StreamFrame(id="r", delta=StreamDelta(content="answer")),
        StreamEndFrame(id="r", finish_reason="stop"),
    ]

    async def gen():
        for f in frames:
            yield f

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_generate_chat = MagicMock(return_value=gen())
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={
            "allowed_model_slugs": ["llama3.2:8b"],
            "api_key_id": "key-1",
            "max_concurrent": 1,
        },
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = [
        ev
        async for ev in adapter.stream_completion(_resolved_conn(), _completion_request())
    ]
    assert any(isinstance(e, ThinkingDelta) and e.delta == "thinking..." for e in events)
    assert any(isinstance(e, ContentDelta) and e.delta == "answer" for e in events)
    assert isinstance(events[-1], StreamDone)


@pytest.mark.asyncio
async def test_stream_completion_translates_tool_call_with_nested_function(monkeypatch):
    """CSP §8.2 wire format nests name/arguments under ``function``. Regression
    test for a bug where the adapter read the top-level keys and always emitted
    an empty tool name, causing ``No executor registered for tool ''``.
    """
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import ToolCallEvent
    from backend.modules.llm._csp._frames import (
        StreamDelta,
        StreamEndFrame,
        StreamFrame,
    )

    frames = [
        StreamFrame(
            id="r",
            delta=StreamDelta(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"loc":"Vienna"}',
                        },
                    }
                ],
            ),
        ),
        StreamEndFrame(id="r", finish_reason="tool_calls"),
    ]

    async def gen():
        for f in frames:
            yield f

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_generate_chat = MagicMock(return_value=gen())
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={
            "allowed_model_slugs": ["llama3.2:8b"],
            "api_key_id": "key-1",
            "max_concurrent": 1,
        },
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = [
        ev
        async for ev in adapter.stream_completion(_resolved_conn(), _completion_request())
    ]
    tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(tool_events) == 1
    assert tool_events[0].id == "call_1"
    assert tool_events[0].name == "get_weather"
    assert tool_events[0].arguments == '{"loc":"Vienna"}'


@pytest.mark.asyncio
async def test_stream_completion_translates_cancelled_to_aborted(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import StreamAborted
    from backend.modules.llm._csp._frames import StreamEndFrame

    async def gen():
        yield StreamEndFrame(id="r", finish_reason="cancelled")

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_generate_chat = MagicMock(return_value=gen())
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={
            "allowed_model_slugs": ["llama3.2:8b"],
            "api_key_id": "key-1",
            "max_concurrent": 1,
        },
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = [
        ev
        async for ev in adapter.stream_completion(_resolved_conn(), _completion_request())
    ]
    assert isinstance(events[-1], StreamAborted)


@pytest.mark.asyncio
async def test_stream_completion_translates_err_frame(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import StreamError
    from backend.modules.llm._csp._frames import ErrFrame

    async def gen():
        yield ErrFrame(id="r", code="model_not_found", message="nope", recoverable=False)

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_generate_chat = MagicMock(return_value=gen())
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access = AsyncMock(
        return_value={
            "allowed_model_slugs": ["llama3.2:8b"],
            "api_key_id": "key-1",
            "max_concurrent": 1,
        },
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    events = [
        ev
        async for ev in adapter.stream_completion(_resolved_conn(), _completion_request())
    ]
    assert any(isinstance(e, StreamError) and e.error_code == "model_not_found" for e in events)


@pytest.mark.asyncio
async def test_stream_completion_refused_when_config_missing(monkeypatch):
    from backend.modules.llm._adapters import _community
    from backend.modules.llm._adapters._events import StreamRefused

    now = datetime.now(UTC)
    empty = ResolvedConnection(
        id="conn-1",
        user_id="u2",
        adapter_type="community",
        display_name="",
        slug="",
        config={"homelab_id": "", "api_key": ""},
        created_at=now,
        updated_at=now,
    )
    adapter = _community.CommunityAdapter()
    events = [
        ev async for ev in adapter.stream_completion(empty, _completion_request())
    ]
    assert len(events) == 1
    assert isinstance(events[0], StreamRefused)


# ----- adapter sub-router (/test, /diagnostics) -----


def _mount_community_router(monkeypatch, resolved: ResolvedConnection):
    """Mount the community adapter router on a minimal FastAPI app and
    override ``resolve_connection_for_user`` so the handlers receive our
    resolved connection without needing auth.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.modules.llm._adapters._community import CommunityAdapter
    from backend.modules.llm._resolver import resolve_connection_for_user

    app = FastAPI()
    router = CommunityAdapter.router()
    assert router is not None, "Community adapter must expose a router"
    app.include_router(router)

    async def _override() -> ResolvedConnection:
        return resolved

    app.dependency_overrides[resolve_connection_for_user] = _override
    return TestClient(app)


def test_router_test_endpoint_reports_valid_with_model_count(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_sidecar = MagicMock()
    fake_sidecar.rpc_list_models = AsyncMock(
        return_value=[
            {"slug": "llama3.2:8b", "display_name": "Llama", "context_length": 131072},
            {"slug": "mistral:7b", "display_name": "Mistral", "context_length": 32768},
        ]
    )
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access_key = AsyncMock(
        return_value={"allowed_model_slugs": ["llama3.2:8b"]},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    client = _mount_community_router(monkeypatch, _resolved_conn())
    resp = client.post("/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["model_count"] == 1
    assert body["total_models_on_homelab"] == 2
    assert isinstance(body["latency_ms"], int)
    assert body["error"] is None


def test_router_test_endpoint_reports_offline(monkeypatch):
    from backend.modules.llm._adapters import _community

    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: None),
    )
    client = _mount_community_router(monkeypatch, _resolved_conn())
    resp = client.post("/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "offline" in body["error"].lower()


def test_router_test_endpoint_reports_key_invalid(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_sidecar = MagicMock()
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access_key = AsyncMock(return_value=None)
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    client = _mount_community_router(monkeypatch, _resolved_conn())
    resp = client.post("/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "api" in body["error"].lower()


def test_router_test_endpoint_missing_config(monkeypatch):
    from backend.modules.llm._adapters import _community

    now = datetime.now(UTC)
    empty = ResolvedConnection(
        id="conn-1", user_id="u2", adapter_type="community",
        display_name="", slug="",
        config={"homelab_id": "", "api_key": ""},
        created_at=now, updated_at=now,
    )
    client = _mount_community_router(monkeypatch, empty)
    resp = client.post("/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False


def test_router_diagnostics_offline(monkeypatch):
    from backend.modules.llm._adapters import _community

    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: None),
    )
    client = _mount_community_router(monkeypatch, _resolved_conn())
    resp = client.get("/diagnostics")
    assert resp.status_code == 200
    assert resp.json() == {"online": False}


def test_router_diagnostics_online_exposes_sidecar_info(monkeypatch):
    from backend.modules.llm._adapters import _community

    fake_sidecar = MagicMock()
    fake_sidecar.sidecar_version = "1.0.0"
    fake_sidecar.engine_info = {"type": "ollama", "version": "0.5.0"}
    fake_sidecar.capabilities = {"chat_streaming"}
    fake_sidecar.max_concurrent = 3
    fake_sidecar.display_name = "Wohnzimmer-GPU"
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )
    client = _mount_community_router(monkeypatch, _resolved_conn())
    resp = client.get("/diagnostics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["sidecar_version"] == "1.0.0"
    assert body["engine"] == {"type": "ollama", "version": "0.5.0"}
    assert body["capabilities"] == ["chat_streaming"]
    assert body["max_concurrent"] == 3
    assert body["display_name"] == "Wohnzimmer-GPU"
