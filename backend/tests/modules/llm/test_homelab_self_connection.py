"""Tests for host-self connections mirrored from homelabs.

These exercise HomelabService's lifecycle coupling to a system-managed
Connection row: create/rename/update max_concurrent_requests/delete, plus
the ConnectionRepository guards against editing system-managed rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import (
    ConnectionRepository,
    ConnectionSystemManagedError,
)
from backend.modules.llm._homelabs import (
    HomelabService,
    HostSlugAlreadyExistsError,
)
from shared.topics import Topics


# -----------------------------------------------------------------------------
# HomelabService create/update/delete coupling to the self-Connection
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_homelab_creates_system_managed_self_connection(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    result = await svc.create_homelab(
        user_id="u1",
        display_name="Alice's GPU",
        host_slug="alices-gpu",
        max_concurrent_requests=5,
    )

    assert result["self_connection_id"]
    conn_repo = ConnectionRepository(test_db)
    conn = await conn_repo.find("u1", result["self_connection_id"])
    assert conn is not None
    assert conn["adapter_type"] == "community"
    assert conn["slug"] == "alices-gpu"
    assert conn["display_name"] == "Alice's GPU"
    assert conn["is_system_managed"] is True
    assert conn["config"]["homelab_id"] == result["homelab"]["homelab_id"]
    assert conn["config"]["is_host_self"] is True
    assert conn["config"]["max_parallel"] == 5
    # No api_key encrypted field (host-self doesn't use one).
    assert conn["config_encrypted"] == {}

    # Both events emitted.
    topics = {call.args[0] for call in bus.publish.call_args_list}
    assert Topics.LLM_HOMELAB_CREATED in topics
    assert Topics.LLM_CONNECTION_CREATED in topics


@pytest.mark.asyncio
async def test_create_homelab_rejects_duplicate_slug(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="dup",
    )
    with pytest.raises(HostSlugAlreadyExistsError) as exc:
        await svc.create_homelab(
            user_id="u1", display_name="B", host_slug="dup",
        )
    assert exc.value.slug == "dup"
    assert exc.value.suggested == "dup-2"


@pytest.mark.asyncio
async def test_rename_homelab_renames_self_connection(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="Old", host_slug="lab",
    )
    await svc.update_homelab(
        user_id="u1",
        homelab_id=created["homelab"]["homelab_id"],
        display_name="New",
    )
    conn = await ConnectionRepository(test_db).find(
        "u1", created["self_connection_id"],
    )
    assert conn["display_name"] == "New"

    # Events emitted: LLM_HOMELAB_UPDATED + LLM_CONNECTION_UPDATED.
    topics = {call.args[0] for call in bus.publish.call_args_list}
    assert Topics.LLM_HOMELAB_UPDATED in topics
    assert Topics.LLM_CONNECTION_UPDATED in topics


@pytest.mark.asyncio
async def test_update_max_concurrent_requests_syncs_self_connection(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1",
        display_name="A",
        host_slug="lab",
        max_concurrent_requests=3,
    )
    await svc.update_homelab(
        user_id="u1",
        homelab_id=created["homelab"]["homelab_id"],
        max_concurrent_requests=9,
    )
    conn = await ConnectionRepository(test_db).find(
        "u1", created["self_connection_id"],
    )
    assert conn["config"]["max_parallel"] == 9


@pytest.mark.asyncio
async def test_delete_homelab_deletes_self_connection(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="lab",
    )
    self_conn_id = created["self_connection_id"]
    await svc.delete_homelab(
        user_id="u1", homelab_id=created["homelab"]["homelab_id"],
    )
    conn = await ConnectionRepository(test_db).find("u1", self_conn_id)
    assert conn is None


# -----------------------------------------------------------------------------
# ConnectionRepository guards against editing system-managed rows
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_repo_update_rejects_system_managed(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="lab",
    )
    repo = ConnectionRepository(test_db)
    with pytest.raises(ConnectionSystemManagedError):
        await repo.update(
            "u1", created["self_connection_id"], display_name="Hacked",
        )


@pytest.mark.asyncio
async def test_connection_repo_delete_rejects_system_managed(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="lab",
    )
    repo = ConnectionRepository(test_db)
    with pytest.raises(ConnectionSystemManagedError):
        await repo.delete("u1", created["self_connection_id"])


@pytest.mark.asyncio
async def test_update_by_system_bypasses_guard(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="lab",
    )
    repo = ConnectionRepository(test_db)
    updated = await repo.update_by_system(
        "u1", created["self_connection_id"], display_name="System-rename",
    )
    assert updated["display_name"] == "System-rename"


# -----------------------------------------------------------------------------
# ApiKey.max_concurrent validation & persistence
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_api_key_stores_max_concurrent(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="lab",
    )
    hid = created["homelab"]["homelab_id"]
    issued = await svc.create_api_key(
        user_id="u1",
        homelab_id=hid,
        display_name="Bob",
        allowed_model_slugs=[],
        max_concurrent=4,
    )
    assert issued["api_key"]["max_concurrent"] == 4


@pytest.mark.asyncio
async def test_update_api_key_updates_max_concurrent(test_db):
    bus = AsyncMock()
    svc = HomelabService(test_db, bus)
    await svc.init()
    created = await svc.create_homelab(
        user_id="u1", display_name="A", host_slug="lab",
    )
    hid = created["homelab"]["homelab_id"]
    issued = await svc.create_api_key(
        user_id="u1",
        homelab_id=hid,
        display_name="Bob",
        allowed_model_slugs=[],
    )
    dto = await svc.update_api_key(
        user_id="u1",
        homelab_id=hid,
        api_key_id=issued["api_key"]["api_key_id"],
        display_name=None,
        allowed_model_slugs=None,
        max_concurrent=7,
    )
    assert dto.max_concurrent == 7


# -----------------------------------------------------------------------------
# CommunityAdapter host-self mode (no DB needed — monkeypatch the sidecar)
# -----------------------------------------------------------------------------


def _host_self_conn() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="self-conn-1",
        user_id="u1",
        adapter_type="community",
        display_name="My GPU",
        slug="my-gpu",
        config={
            "homelab_id": "Xk7bQ2eJn9m",
            "is_host_self": True,
            "max_parallel": 3,
        },
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_host_self_fetch_models_bypasses_allowlist(monkeypatch):
    """Host-self: no api-key is required, every model the sidecar reports is
    returned without allowlist filtering.
    """
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
        ],
    )
    monkeypatch.setattr(
        _community, "get_sidecar_registry",
        lambda: MagicMock(get=lambda _hid: fake_sidecar),
    )

    # validate_consumer_access_key MUST NOT be called for host-self. Set an
    # assertion-side-effect to fail loudly if it is.
    fake_svc = MagicMock()
    fake_svc.validate_consumer_access_key = AsyncMock(
        side_effect=AssertionError("must not be called for host-self"),
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    adapter = _community.CommunityAdapter()
    out = await adapter.fetch_models(_host_self_conn())
    # Both models visible — no allowlist applied.
    assert sorted(m.model_id for m in out) == ["llama3.2:8b", "mistral:7b"]


@pytest.mark.asyncio
async def test_host_self_stream_completion_bypasses_api_key_check(monkeypatch):
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
    from shared.dtos.inference import (
        CompletionMessage,
        CompletionRequest,
        ContentPart,
    )

    frames = [
        StreamFrame(id="r", delta=StreamDelta(content="hello")),
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
        side_effect=AssertionError("must not be called for host-self"),
    )
    fake_svc.find_homelab_by_id = AsyncMock(
        return_value={"max_concurrent_requests": 3},
    )
    monkeypatch.setattr(_community, "_homelab_service", lambda: fake_svc)

    req = CompletionRequest(
        model="llama3.2:8b",
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
    )
    adapter = _community.CommunityAdapter()
    events = [ev async for ev in adapter.stream_completion(_host_self_conn(), req)]
    deltas = [e for e in events if isinstance(e, ContentDelta)]
    assert [d.delta for d in deltas] == ["hello"]
    assert isinstance(events[-1], StreamDone)
