"""End-to-end test for Community Provisioning.

Exercises the full stack from a consumer's point of view:

1. Host creates a Homelab via ``HomelabService`` against a real MongoDB.
2. Host issues an API-Key with a one-element allowlist.
3. A fake sidecar (``FakeWS``) handshakes against the real
   ``/ws/sidecar`` endpoint, registering a live ``SidecarConnection`` in
   the process-local ``SidecarRegistry``.
4. The fake sidecar answers the ``list_models`` RPC with one model.
5. The community adapter's ``fetch_models`` is invoked with a
   ``ResolvedConnection`` carrying the host's homelab_id + api_key.
6. We assert the adapter returned the single allowlisted model with the
   consumer connection's identity preserved on the DTO.

This skips the HTTP / REST layer by construction — the REST surface is
a thin wrapper around the adapter and is already exercised by the unit
tests for each layer.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from backend.modules.llm._adapters._community import CommunityAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._csp._registry import (
    SidecarRegistry,
    set_sidecar_registry,
)
from backend.modules.llm._homelabs import HomelabService
from backend.ws import sidecar_router as sr


class FakeWS:
    """Starlette-WebSocket-shaped stand-in used to drive ``sidecar_endpoint``
    directly from an asyncio test without standing up a full ASGI harness.
    """

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.query_params: dict[str, str] = {}
        self._from_client: asyncio.Queue[str | None] = asyncio.Queue()
        self._to_client: asyncio.Queue[str] = asyncio.Queue()
        self.close_code: int | None = None
        self.application_state = WebSocketState.CONNECTING

    async def accept(self) -> None:
        self.application_state = WebSocketState.CONNECTED

    async def receive_text(self) -> str:
        v = await self._from_client.get()
        if v is None:
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect(code=1000)
        return v

    async def send_text(self, text: str) -> None:
        await self._to_client.put(text)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code
        self.application_state = WebSocketState.DISCONNECTED

    # --- test helpers ---

    def feed(self, payload: dict) -> None:
        self._from_client.put_nowait(json.dumps(payload))

    def feed_raw(self, text: str) -> None:
        self._from_client.put_nowait(text)

    def disconnect(self) -> None:
        self._from_client.put_nowait(None)

    async def recv_json(self) -> dict:
        return json.loads(await self._to_client.get())


@pytest.mark.asyncio
async def test_community_e2e_fetch_models(test_db, monkeypatch):
    # --- 1. Host creates homelab + api-key ------------------------------
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()

    created = await svc.create_homelab(user_id="u_host", display_name="Wohnzimmer-GPU")
    homelab_id = created["homelab"]["homelab_id"]
    host_key = created["plaintext_host_key"]

    issued = await svc.create_api_key(
        user_id="u_host",
        homelab_id=homelab_id,
        display_name="Bob",
        allowed_model_slugs=["llama3.2:8b"],
    )
    api_key = issued["plaintext_api_key"]

    # --- 2. Stand up a fresh SidecarRegistry for this test -------------
    registry = SidecarRegistry(event_bus=AsyncMock())
    set_sidecar_registry(registry)
    monkeypatch.setattr(sr, "get_db", lambda: test_db)
    monkeypatch.setattr(sr, "get_event_bus", lambda: AsyncMock())

    # The adapter's _homelab_service() pulls get_db / get_event_bus from
    # process globals that are not wired up in pytest; patch the factory
    # so validate_consumer_access_key sees the real test database.
    from backend.modules.llm._adapters import _community as _community_mod

    def _fake_homelab_service() -> HomelabService:
        return HomelabService(test_db, AsyncMock())

    monkeypatch.setattr(_community_mod, "_homelab_service", _fake_homelab_service)

    # --- 3. Drive the sidecar endpoint on a background task ------------
    ws = FakeWS(headers={"authorization": f"Bearer {host_key}"})

    # Handshake comes from the "sidecar" — matching the server's CSP/1.0.
    ws.feed({
        "type": "handshake",
        "csp_version": "1.0",
        "sidecar_version": "1.0.0",
        "engine": {"type": "ollama", "version": "0.5.0"},
        "max_concurrent_requests": 2,
        "capabilities": ["chat_streaming"],
    })

    endpoint_task = asyncio.create_task(sr.sidecar_endpoint(ws))

    # Read the handshake_ack — prove the sidecar is registered.
    ack = await asyncio.wait_for(ws.recv_json(), timeout=2.0)
    assert ack["type"] == "handshake_ack"
    assert ack["accepted"] is True
    assert ack["homelab_id"] == homelab_id

    # Give the endpoint a moment to enter its run() loop.
    for _ in range(20):
        if registry.get(homelab_id) is not None:
            break
        await asyncio.sleep(0.01)
    assert registry.get(homelab_id) is not None, "sidecar did not register"

    # --- 4. Kick off a consumer-side fetch_models call -----------------
    now = datetime.now(UTC)
    consumer_conn = ResolvedConnection(
        id="consumer-conn-1",
        user_id="u_consumer",
        adapter_type="community",
        display_name="Alice's Homelab",
        slug="alices-homelab",
        config={"homelab_id": homelab_id, "api_key": api_key},
        created_at=now,
        updated_at=now,
    )
    adapter = CommunityAdapter()

    # Fire the fetch in a background task so we can answer the RPC on the
    # fake-sidecar side.
    fetch_task = asyncio.create_task(adapter.fetch_models(consumer_conn))

    # Wait for the list_models request frame to arrive on the "sidecar" side.
    req = await asyncio.wait_for(ws.recv_json(), timeout=2.0)
    assert req["type"] == "req"
    assert req["op"] == "list_models"

    # Answer it.
    ws.feed({
        "type": "res",
        "id": req["id"],
        "ok": True,
        "body": {
            "models": [
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
            ],
        },
    })

    # --- 5. Assert on the adapter result -------------------------------
    models = await asyncio.wait_for(fetch_task, timeout=2.0)
    assert len(models) == 1
    assert models[0].model_id == "llama3.2:8b"
    assert models[0].connection_id == "consumer-conn-1"
    assert models[0].connection_slug == "alices-homelab"
    assert models[0].connection_display_name == "Alice's Homelab"
    assert models[0].context_window == 131072

    # --- 6. Tidy up the background endpoint task -----------------------
    ws.disconnect()
    await asyncio.wait_for(endpoint_task, timeout=2.0)
    # The endpoint cleans up after itself — the registry slot is released.
    assert registry.get(homelab_id) is None
    set_sidecar_registry(None)  # type: ignore[arg-type]
