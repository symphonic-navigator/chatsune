"""Tests for the /ws/sidecar endpoint.

Path B: these tests invoke the handler directly with a ``FakeWS`` stand-in
that matches the subset of the Starlette WebSocket API the handler uses.
That avoids wiring up a full ``TestClient`` + auth session just to exercise
handshake and registry plumbing — see the plan's Path-A vs Path-B note.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from backend.modules.llm import HomelabService
from backend.modules.llm._csp._registry import (
    SidecarRegistry,
    get_sidecar_registry,
    set_sidecar_registry,
)
from backend.ws import sidecar_router as sr
from starlette.websockets import WebSocketState


class FakeWS:
    """Minimal Starlette-WebSocket-shaped object for exercising the handler."""

    def __init__(self, headers: dict[str, str] | None = None,
                 query: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.query_params = query or {}
        self._from_client: asyncio.Queue[str | None] = asyncio.Queue()
        self._to_client: list[str] = []
        self._accepted = False
        self.close_code: int | None = None
        self.application_state = WebSocketState.CONNECTING

    async def accept(self) -> None:
        self._accepted = True
        self.application_state = WebSocketState.CONNECTED

    async def receive_text(self) -> str:
        v = await self._from_client.get()
        if v is None:
            # mimic disconnect
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect(code=1000)
        return v

    async def send_text(self, text: str) -> None:
        self._to_client.append(text)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code
        self.application_state = WebSocketState.DISCONNECTED

    # test helpers
    def feed(self, payload: dict) -> None:
        self._from_client.put_nowait(json.dumps(payload))

    def disconnect(self) -> None:
        self._from_client.put_nowait(None)

    def last_sent(self) -> dict:
        return json.loads(self._to_client[-1])


def _handshake_payload(max_concurrent: int = 2,
                       csp_version: str = "1.0") -> dict:
    return {
        "type": "handshake",
        "csp_version": csp_version,
        "sidecar_version": "1.0.0",
        "engine": {"type": "ollama", "version": "0.5.0"},
        "max_concurrent_requests": max_concurrent,
        "capabilities": ["chat_streaming"],
    }


@pytest.fixture
def registry():
    reg = SidecarRegistry(event_bus=AsyncMock())
    set_sidecar_registry(reg)
    yield reg
    set_sidecar_registry(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rejects_connect_without_auth(monkeypatch, registry):
    ws = FakeWS(headers={})
    await sr.sidecar_endpoint(ws)
    assert ws.close_code == 4401
    assert ws._accepted is False


@pytest.mark.asyncio
async def test_rejects_wrong_prefix(monkeypatch, registry):
    ws = FakeWS(headers={"authorization": "Bearer invalid"})

    # With an invalid (non-cshost_) token, we must short-circuit before
    # HomelabService gets touched. Supplying a stub service makes it
    # obvious if the guard is accidentally skipped.
    class StubService:
        async def resolve_homelab_by_host_key(self, *_args, **_kwargs):
            raise AssertionError("must not be called for wrong-prefix tokens")

    monkeypatch.setattr(sr, "HomelabService", lambda *_a, **_kw: StubService())
    monkeypatch.setattr(sr, "get_db", lambda: None)
    monkeypatch.setattr(sr, "get_event_bus", lambda: None)

    await sr.sidecar_endpoint(ws)
    assert ws.close_code == 4401


@pytest.mark.asyncio
async def test_rejects_unknown_host_key(monkeypatch, registry):
    ws = FakeWS(headers={"authorization": "Bearer cshost_unknown"})

    class StubService:
        async def resolve_homelab_by_host_key(self, plaintext):
            return None

    monkeypatch.setattr(sr, "HomelabService", lambda *_a, **_kw: StubService())
    monkeypatch.setattr(sr, "get_db", lambda: None)
    monkeypatch.setattr(sr, "get_event_bus", lambda: None)

    await sr.sidecar_endpoint(ws)
    assert ws.close_code == 4401


@pytest.mark.asyncio
async def test_handshake_happy_path(monkeypatch, registry):
    ws = FakeWS(headers={"authorization": "Bearer cshost_valid"})

    homelab = {
        "homelab_id": "H1",
        "user_id": "u1",
        "display_name": "HL",
        "status": "active",
    }
    touched: dict = {}

    class StubRepo:
        async def touch_last_seen(self, *, homelab_id, sidecar_version, engine_info):
            touched["homelab_id"] = homelab_id
            touched["sidecar_version"] = sidecar_version
            touched["engine_info"] = engine_info

    class StubService:
        def __init__(self) -> None:
            self._homelabs = StubRepo()

        async def resolve_homelab_by_host_key(self, plaintext):
            return homelab

    monkeypatch.setattr(sr, "HomelabService", lambda *_a, **_kw: StubService())
    monkeypatch.setattr(sr, "get_db", lambda: None)
    monkeypatch.setattr(sr, "get_event_bus", lambda: None)

    ws.feed(_handshake_payload())
    # finish the run() loop once handshake + register are done
    ws.disconnect()

    await sr.sidecar_endpoint(ws)

    ack = json.loads(ws._to_client[0])
    assert ack["type"] == "handshake_ack"
    assert ack["accepted"] is True
    assert ack["homelab_id"] == "H1"
    assert ack["display_name"] == "HL"
    assert touched["homelab_id"] == "H1"
    # Registry should have been cleaned up after run() exited.
    assert registry.get("H1") is None


@pytest.mark.asyncio
async def test_handshake_rejects_major_version_mismatch(monkeypatch, registry):
    ws = FakeWS(headers={"authorization": "Bearer cshost_valid"})

    homelab = {
        "homelab_id": "H1",
        "user_id": "u1",
        "display_name": "HL",
        "status": "active",
    }

    class StubRepo:
        async def touch_last_seen(self, **_kwargs):
            raise AssertionError("touch_last_seen must not run on rejected handshake")

    class StubService:
        def __init__(self) -> None:
            self._homelabs = StubRepo()

        async def resolve_homelab_by_host_key(self, plaintext):
            return homelab

    monkeypatch.setattr(sr, "HomelabService", lambda *_a, **_kw: StubService())
    monkeypatch.setattr(sr, "get_db", lambda: None)
    monkeypatch.setattr(sr, "get_event_bus", lambda: None)

    ws.feed(_handshake_payload(csp_version="2.0"))

    await sr.sidecar_endpoint(ws)

    ack = json.loads(ws._to_client[0])
    assert ack["accepted"] is False
    assert any("version_unsupported" in n for n in ack.get("notices", []))
    assert ws.close_code == 1002
    assert registry.get("H1") is None


@pytest.mark.asyncio
async def test_list_models_roundtrip_over_handler(monkeypatch, registry):
    """End-to-end: register via handler, drive an RPC through the registry."""

    ws = FakeWS(headers={"authorization": "Bearer cshost_valid"})

    homelab = {
        "homelab_id": "H1",
        "user_id": "u1",
        "display_name": "HL",
        "status": "active",
    }

    class StubRepo:
        async def touch_last_seen(self, **_kwargs):
            pass

    class StubService:
        def __init__(self) -> None:
            self._homelabs = StubRepo()

        async def resolve_homelab_by_host_key(self, plaintext):
            return homelab

    monkeypatch.setattr(sr, "HomelabService", lambda *_a, **_kw: StubService())
    monkeypatch.setattr(sr, "get_db", lambda: None)
    monkeypatch.setattr(sr, "get_event_bus", lambda: None)

    handler_task = asyncio.create_task(sr.sidecar_endpoint(ws))

    # First, feed the handshake.
    ws.feed(_handshake_payload())

    # Wait for the ack before we try to use the registry.
    for _ in range(100):
        if ws._to_client:
            break
        await asyncio.sleep(0.01)
    assert ws._to_client, "no handshake_ack emitted"

    # Wait until the registry has registered the connection.
    for _ in range(100):
        if registry.get("H1") is not None:
            break
        await asyncio.sleep(0.01)

    conn = registry.get("H1")
    assert conn is not None

    async def sidecar_emulator() -> None:
        # Wait for the req frame to arrive in the handler's outbound buffer.
        for _ in range(100):
            if len(ws._to_client) >= 2:
                break
            await asyncio.sleep(0.01)
        req = json.loads(ws._to_client[-1])
        assert req["type"] == "req"
        assert req["op"] == "list_models"
        ws.feed(
            {
                "type": "res",
                "id": req["id"],
                "ok": True,
                "body": {
                    "models": [
                        {
                            "slug": "llama3.2:8b",
                            "display_name": "Llama",
                            "context_length": 131072,
                            "capabilities": ["text"],
                        }
                    ]
                },
            }
        )

    sidecar_task = asyncio.create_task(sidecar_emulator())
    models = await asyncio.wait_for(conn.rpc_list_models(), timeout=5.0)
    await sidecar_task
    assert models[0]["slug"] == "llama3.2:8b"

    ws.disconnect()
    await asyncio.wait_for(handler_task, timeout=5.0)
    assert registry.get("H1") is None
