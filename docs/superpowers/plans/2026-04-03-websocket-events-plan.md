# WebSocket Infrastructure & Event Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement WebSocket connection management, an in-process event bus with Redis Streams persistence, and wire all user/audit events through it so every admin and affected user receives live updates.

**Architecture:** One WebSocket connection per authenticated user. Events are published via `EventBus.publish()`, written to a Redis Stream (stream ID becomes the sequence number), then fanned out in-memory to connected clients. On reconnect the client provides its `last_sequence` and the backend replays missed events from the stream.

**Tech Stack:** FastAPI WebSocket, redis-py v5 (async), Pydantic v2, pytest + starlette TestClient for WS tests.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `shared/events/base.py` | Create | BaseEvent envelope model |
| `shared/events/audit.py` | Create | AuditLoggedEvent |
| `shared/topics.py` | Modify | Add `AUDIT_LOGGED` |
| `backend/ws/__init__.py` | Create | Empty package marker |
| `backend/ws/manager.py` | Create | ConnectionManager + singleton + getter |
| `backend/ws/event_bus.py` | Create | EventBus + fan-out rules + singleton + getter |
| `backend/ws/router.py` | Create | `/ws` endpoint, auth handshake, ping, token refresh |
| `backend/main.py` | Modify | Init singletons in lifespan, include ws router |
| `backend/modules/user/__init__.py` | Modify | Expose `perform_token_refresh` |
| `backend/modules/user/_handlers.py` | Modify | Inject event_bus, publish events |
| `tests/ws/__init__.py` | Create | Empty package marker |
| `tests/ws/test_manager.py` | Create | ConnectionManager unit tests |
| `tests/ws/test_event_bus.py` | Create | EventBus unit tests (mocked Redis + manager) |
| `tests/ws/test_router.py` | Create | WS router integration tests (real Redis, TestClient) |

---

## Task 1: Shared Foundations

**Files:**
- Create: `shared/events/base.py`
- Create: `shared/events/audit.py`
- Modify: `shared/topics.py`
- Create: `tests/ws/__init__.py`

- [ ] **Step 1: Write failing tests for BaseEvent and AuditLoggedEvent**

```python
# tests/test_shared_events.py
import json
from datetime import datetime, timezone
from shared.events.base import BaseEvent
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics


def test_base_event_has_required_fields():
    event = BaseEvent(
        type="user.created",
        scope="global",
        correlation_id="corr-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        payload={"user_id": "u1"},
    )
    assert event.type == "user.created"
    assert event.scope == "global"
    assert event.sequence == ""
    assert len(event.id) > 0


def test_base_event_id_is_unique():
    a = BaseEvent(type="x", scope="global", correlation_id="c", timestamp=datetime.now(timezone.utc), payload={})
    b = BaseEvent(type="x", scope="global", correlation_id="c", timestamp=datetime.now(timezone.utc), payload={})
    assert a.id != b.id


def test_base_event_sequence_is_mutable():
    event = BaseEvent(type="x", scope="global", correlation_id="c", timestamp=datetime.now(timezone.utc), payload={})
    event.sequence = "1735000000000-0"
    assert event.sequence == "1735000000000-0"


def test_audit_logged_event():
    event = AuditLoggedEvent(
        actor_id="user1",
        action="user.created",
        resource_type="user",
        resource_id="user2",
        detail={"role": "admin"},
    )
    assert event.actor_id == "user1"
    assert event.action == "user.created"


def test_topics_audit_logged_constant():
    assert Topics.AUDIT_LOGGED == "audit.logged"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/chris/workspace/chatsune
docker compose exec backend python -m pytest ../tests/test_shared_events.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'shared.events.base'`

- [ ] **Step 3: Create `shared/events/base.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    sequence: str = ""  # set by EventBus after XADD
    scope: str = "global"
    correlation_id: str
    timestamp: datetime
    payload: dict
```

- [ ] **Step 4: Create `shared/events/audit.py`**

```python
from pydantic import BaseModel


class AuditLoggedEvent(BaseModel):
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict | None = None
```

- [ ] **Step 5: Add `AUDIT_LOGGED` to `shared/topics.py`**

Current file content:
```python
class Topics:
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_PASSWORD_RESET = "user.password_reset"
    ERROR = "error"
```

Replace with:
```python
class Topics:
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_PASSWORD_RESET = "user.password_reset"
    AUDIT_LOGGED = "audit.logged"
    ERROR = "error"
```

- [ ] **Step 6: Create empty `tests/ws/__init__.py`**

```python
```

- [ ] **Step 7: Run tests to confirm they pass**

```bash
docker compose exec backend python -m pytest ../tests/test_shared_events.py -v 2>&1 | tail -20
```

Expected: all 5 tests PASS

- [ ] **Step 8: Commit**

```bash
git add shared/events/base.py shared/events/audit.py shared/topics.py tests/ws/__init__.py tests/test_shared_events.py
git commit -m "Add BaseEvent envelope, AuditLoggedEvent and AUDIT_LOGGED topic"
```

---

## Task 2: ConnectionManager

**Files:**
- Create: `backend/ws/__init__.py`
- Create: `backend/ws/manager.py`
- Create: `tests/ws/test_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/ws/test_manager.py
from unittest.mock import AsyncMock, MagicMock
import pytest
from backend.ws.manager import ConnectionManager


def make_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


async def test_connect_registers_user():
    mgr = ConnectionManager()
    ws = make_ws()
    await mgr.connect("user1", "user", ws)
    assert "user1" in mgr._connections
    assert mgr._user_roles["user1"] == "user"


async def test_disconnect_removes_connection():
    mgr = ConnectionManager()
    ws = make_ws()
    await mgr.connect("user1", "user", ws)
    await mgr.disconnect("user1", ws)
    assert "user1" not in mgr._connections
    assert "user1" not in mgr._user_roles


async def test_disconnect_keeps_entry_when_other_sessions_remain():
    mgr = ConnectionManager()
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect("user1", "user", ws1)
    await mgr.connect("user1", "user", ws2)
    await mgr.disconnect("user1", ws1)
    assert "user1" in mgr._connections
    assert ws1 not in mgr._connections["user1"]
    assert ws2 in mgr._connections["user1"]


async def test_send_to_user_delivers_event():
    mgr = ConnectionManager()
    ws = make_ws()
    await mgr.connect("user1", "user", ws)
    await mgr.send_to_user("user1", {"type": "test"})
    ws.send_json.assert_awaited_once_with({"type": "test"})


async def test_send_to_user_ignores_missing_user():
    mgr = ConnectionManager()
    # Should not raise
    await mgr.send_to_user("nonexistent", {"type": "test"})


async def test_send_to_users_delivers_to_all():
    mgr = ConnectionManager()
    ws1, ws2 = make_ws(), make_ws()
    await mgr.connect("user1", "user", ws1)
    await mgr.connect("user2", "user", ws2)
    await mgr.send_to_users(["user1", "user2"], {"type": "test"})
    ws1.send_json.assert_awaited_once()
    ws2.send_json.assert_awaited_once()


async def test_broadcast_to_roles_only_sends_to_matching_role():
    mgr = ConnectionManager()
    admin_ws = make_ws()
    user_ws = make_ws()
    await mgr.connect("admin1", "admin", admin_ws)
    await mgr.connect("user1", "user", user_ws)
    await mgr.broadcast_to_roles(["admin"], {"type": "test"})
    admin_ws.send_json.assert_awaited_once_with({"type": "test"})
    user_ws.send_json.assert_not_awaited()


async def test_broadcast_to_multiple_roles():
    mgr = ConnectionManager()
    admin_ws = make_ws()
    master_ws = make_ws()
    user_ws = make_ws()
    await mgr.connect("admin1", "admin", admin_ws)
    await mgr.connect("master1", "master_admin", master_ws)
    await mgr.connect("user1", "user", user_ws)
    await mgr.broadcast_to_roles(["admin", "master_admin"], {"type": "test"})
    admin_ws.send_json.assert_awaited_once()
    master_ws.send_json.assert_awaited_once()
    user_ws.send_json.assert_not_awaited()


def test_user_ids_by_role():
    mgr = ConnectionManager()
    mgr._user_roles = {"a1": "admin", "m1": "master_admin", "u1": "user"}
    result = mgr.user_ids_by_role("admin")
    assert result == ["a1"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_manager.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'backend.ws'`

- [ ] **Step 3: Create `backend/ws/__init__.py`**

```python
```

- [ ] **Step 4: Create `backend/ws/manager.py`**

```python
from fastapi import WebSocket

_manager: "ConnectionManager | None" = None


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._user_roles: dict[str, str] = {}

    async def connect(self, user_id: str, role: str, ws: WebSocket) -> None:
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(ws)
        self._user_roles[user_id] = role

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        if user_id not in self._connections:
            return
        self._connections[user_id].discard(ws)
        if not self._connections[user_id]:
            del self._connections[user_id]
            del self._user_roles[user_id]

    async def send_to_user(self, user_id: str, event: dict) -> None:
        for ws in list(self._connections.get(user_id, set())):
            try:
                await ws.send_json(event)
            except Exception:
                pass

    async def send_to_users(self, user_ids: list[str], event: dict) -> None:
        for user_id in user_ids:
            await self.send_to_user(user_id, event)

    async def broadcast_to_roles(self, roles: list[str], event: dict) -> None:
        for user_id, role in list(self._user_roles.items()):
            if role in roles:
                await self.send_to_user(user_id, event)

    def user_ids_by_role(self, role: str) -> list[str]:
        return [uid for uid, r in self._user_roles.items() if r == role]


def set_manager(manager: ConnectionManager) -> None:
    global _manager
    _manager = manager


def get_manager() -> ConnectionManager:
    assert _manager is not None, "ConnectionManager not initialised"
    return _manager
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_manager.py -v 2>&1 | tail -15
```

Expected: all 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/ws/__init__.py backend/ws/manager.py tests/ws/test_manager.py
git commit -m "Add ConnectionManager with role-based broadcast"
```

---

## Task 3: EventBus

**Files:**
- Create: `backend/ws/event_bus.py`
- Create: `tests/ws/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/ws/test_event_bus.py
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from backend.ws.event_bus import EventBus
from backend.ws.manager import ConnectionManager
from shared.events.auth import UserCreatedEvent, UserUpdatedEvent, UserDeactivatedEvent
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics


def make_redis():
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1735000000000-0")
    redis.xtrim = AsyncMock()
    return redis


def make_manager():
    manager = MagicMock(spec=ConnectionManager)
    manager._user_roles = {}
    manager.broadcast_to_roles = AsyncMock()
    manager.send_to_users = AsyncMock()
    manager.send_to_user = AsyncMock()
    manager.user_ids_by_role = MagicMock(return_value=[])
    return manager


def make_event():
    return UserCreatedEvent(
        user_id="u1", username="alice", role="user",
        timestamp=datetime.now(timezone.utc),
    )


async def test_publish_calls_xadd_with_stream_key():
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(Topics.USER_CREATED, make_event())
    redis.xadd.assert_awaited_once()
    assert redis.xadd.call_args[0][0] == "events:global"


async def test_publish_calls_xtrim_for_24h_retention():
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(Topics.USER_CREATED, make_event())
    redis.xtrim.assert_awaited_once()
    call_kwargs = redis.xtrim.call_args
    assert call_kwargs[0][0] == "events:global"


async def test_publish_sets_sequence_from_stream_id():
    redis = make_redis()
    redis.xadd = AsyncMock(return_value="1735111111111-0")
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    await bus.publish(Topics.USER_CREATED, make_event())
    # The broadcast call should contain the sequence in the envelope
    call_args = manager.broadcast_to_roles.call_args
    event_dict = call_args[0][1]
    assert event_dict["sequence"] == "1735111111111-0"


async def test_user_created_broadcasts_to_admins_only():
    redis = make_redis()
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    await bus.publish(Topics.USER_CREATED, make_event(), target_user_ids=["u1"])
    manager.broadcast_to_roles.assert_awaited_once_with(
        ["admin", "master_admin"], ANY
    )
    manager.send_to_users.assert_not_awaited()


async def test_user_updated_broadcasts_to_admins_and_target():
    redis = make_redis()
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = UserUpdatedEvent(
        user_id="u1", changes={"display_name": "Bob"},
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(Topics.USER_UPDATED, event, target_user_ids=["u1"])
    manager.broadcast_to_roles.assert_awaited_once_with(
        ["admin", "master_admin"], ANY
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_audit_logged_sends_to_master_admin_always():
    redis = make_redis()
    manager = make_manager()
    manager.user_ids_by_role = MagicMock(return_value=[])
    bus = EventBus(redis=redis, manager=manager)
    event = AuditLoggedEvent(
        actor_id="admin1", action="user.created",
        resource_type="user", resource_id="u1",
    )
    await bus.publish(Topics.AUDIT_LOGGED, event)
    manager.broadcast_to_roles.assert_awaited_once_with(["master_admin"], ANY)


async def test_audit_logged_sends_to_admin_only_if_actor_matches():
    redis = make_redis()
    manager = make_manager()
    # admin1 is the actor, admin2 is not
    manager.user_ids_by_role = MagicMock(return_value=["admin1", "admin2"])
    bus = EventBus(redis=redis, manager=manager)
    event = AuditLoggedEvent(
        actor_id="admin1", action="user.created",
        resource_type="user", resource_id="u1",
    )
    await bus.publish(Topics.AUDIT_LOGGED, event)
    # Only admin1 (the actor) gets it, not admin2
    manager.send_to_user.assert_awaited_once_with("admin1", ANY)


async def test_publish_uses_custom_scope():
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(Topics.USER_CREATED, make_event(), scope="custom")
    assert redis.xadd.call_args[0][0] == "events:custom"
    assert redis.xtrim.call_args[0][0] == "events:custom"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_event_bus.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'backend.ws.event_bus'`

- [ ] **Step 3: Create `backend/ws/event_bus.py`**

```python
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel
from redis.asyncio import Redis

from backend.ws.manager import ConnectionManager
from shared.events.base import BaseEvent
from shared.topics import Topics

_TWENTY_FOUR_HOURS_MS = 86_400_000

# (roles_to_broadcast, also_send_to_target_user_ids)
_FANOUT: dict[str, tuple[list[str], bool]] = {
    Topics.USER_CREATED: (["admin", "master_admin"], False),
    Topics.USER_UPDATED: (["admin", "master_admin"], True),
    Topics.USER_DEACTIVATED: (["admin", "master_admin"], True),
    Topics.USER_PASSWORD_RESET: (["admin", "master_admin"], True),
}

_bus: "EventBus | None" = None


class EventBus:
    def __init__(self, redis: Redis, manager: ConnectionManager) -> None:
        self._redis = redis
        self._manager = manager

    async def publish(
        self,
        topic: str,
        event: BaseModel,
        scope: str = "global",
        target_user_ids: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        envelope = BaseEvent(
            type=topic,
            scope=scope,
            correlation_id=correlation_id or str(uuid4()),
            timestamp=now,
            payload=event.model_dump(mode="json"),
        )

        stream_key = f"events:{scope}"
        stream_id = await self._redis.xadd(
            stream_key, {"envelope": envelope.model_dump_json()}
        )
        envelope.sequence = stream_id

        now_ms = int(now.timestamp() * 1000)
        await self._redis.xtrim(
            stream_key, minid=str(now_ms - _TWENTY_FOUR_HOURS_MS)
        )

        await self._fan_out(
            topic, envelope.model_dump(mode="json"), target_user_ids or []
        )

    async def _fan_out(
        self, topic: str, event_dict: dict, target_user_ids: list[str]
    ) -> None:
        if topic == Topics.AUDIT_LOGGED:
            await self._fan_out_audit(event_dict)
            return

        if topic not in _FANOUT:
            return

        roles, send_to_targets = _FANOUT[topic]
        await self._manager.broadcast_to_roles(roles, event_dict)
        if send_to_targets and target_user_ids:
            await self._manager.send_to_users(target_user_ids, event_dict)

    async def _fan_out_audit(self, event_dict: dict) -> None:
        actor_id = event_dict.get("payload", {}).get("actor_id", "")
        await self._manager.broadcast_to_roles(["master_admin"], event_dict)
        for admin_id in self._manager.user_ids_by_role("admin"):
            if admin_id == actor_id:
                await self._manager.send_to_user(admin_id, event_dict)


def set_event_bus(bus: "EventBus") -> None:
    global _bus
    _bus = bus


def get_event_bus() -> "EventBus":
    assert _bus is not None, "EventBus not initialised"
    return _bus
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_event_bus.py -v 2>&1 | tail -15
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ws/event_bus.py tests/ws/test_event_bus.py
git commit -m "Add EventBus with Redis Streams persistence and role-based fan-out"
```

---

## Task 4: WebSocket Router

**Files:**
- Create: `backend/ws/router.py`
- Create: `tests/ws/test_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/ws/test_router.py
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.modules.user._auth import create_access_token, generate_session_id


def valid_token(role: str = "user", mcp: bool = False) -> str:
    return create_access_token(
        user_id="test-user-id",
        role=role,
        session_id=generate_session_id(),
        must_change_password=mcp,
    )


@pytest.fixture
def ws_client():
    with TestClient(app) as client:
        yield client


def test_ws_rejects_missing_token(ws_client):
    with pytest.raises(Exception):
        with ws_client.websocket_connect("/ws"):
            pass


def test_ws_rejects_invalid_token(ws_client):
    with pytest.raises(Exception):
        with ws_client.websocket_connect("/ws?token=not-a-jwt"):
            pass


def test_ws_rejects_mcp_token(ws_client):
    token = valid_token(mcp=True)
    with pytest.raises(Exception):
        with ws_client.websocket_connect(f"/ws?token={token}"):
            pass


def test_ws_accepts_valid_token_and_responds_to_ping(ws_client):
    token = valid_token(role="user")
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_ws_ignores_unknown_message_types(ws_client):
    token = valid_token(role="user")
    with ws_client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_json({"type": "unknown_type"})
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_ws_replays_missed_events_on_reconnect(ws_client):
    """Connect, capture a stream ID, disconnect, reconnect with since= and verify replay."""
    import json
    from redis.asyncio import Redis
    from backend.config import settings
    import asyncio

    # Manually insert an event into the stream
    async def seed_stream():
        r = Redis.from_url(settings.redis_uri, decode_responses=True)
        stream_id = await r.xadd(
            "events:global",
            {"envelope": json.dumps({
                "id": "evt-1",
                "type": "user.created",
                "sequence": "",
                "scope": "global",
                "correlation_id": "corr-1",
                "timestamp": "2026-04-03T00:00:00+00:00",
                "payload": {"user_id": "u1"},
            })}
        )
        await r.aclose()
        return stream_id

    stream_id = asyncio.get_event_loop().run_until_complete(seed_stream())

    # Fake a "last seen" ID just before the seeded event by using "0-0"
    token = valid_token(role="admin")
    with ws_client.websocket_connect(f"/ws?token={token}&since=0-0") as ws:
        data = ws.receive_json()
        assert data["type"] == "user.created"
        assert data["sequence"] == stream_id
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_router.py -v 2>&1 | tail -10
```

Expected: failures because `/ws` route does not exist yet

- [ ] **Step 3: Create `backend/ws/router.py`**

```python
import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.modules.user._auth import decode_access_token
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(
    ws: WebSocket,
    token: str = Query(...),
    since: str | None = Query(default=None),
) -> None:
    try:
        payload = decode_access_token(token)
    except Exception:
        await ws.close(code=4001)
        return

    if payload.get("mcp"):
        await ws.close(code=4003)
        return

    user_id: str = payload["sub"]
    role: str = payload["role"]
    exp: int = payload["exp"]

    manager = get_manager()
    await ws.accept()
    await manager.connect(user_id, role, ws)

    if since is not None:
        redis = get_event_bus()._redis
        entries = await redis.xrange("events:global", min=f"({since}", max="+")
        for stream_id, data in entries:
            try:
                envelope = json.loads(data["envelope"])
                envelope["sequence"] = stream_id
                await ws.send_json(envelope)
            except Exception:
                pass

    async def _send_expiry_warning() -> None:
        now = datetime.now(timezone.utc).timestamp()
        delay = exp - 120 - now
        if delay > 0:
            await asyncio.sleep(delay)
            try:
                await ws.send_json({"type": "token.expiring_soon"})
            except Exception:
                pass

    expiry_task = asyncio.create_task(_send_expiry_warning())

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "token.refresh":
                refresh_token = ws.cookies.get("refresh_token")
                if not refresh_token:
                    await ws.send_json({"type": "error", "detail": "No refresh token cookie"})
                    continue
                from backend.modules.user import perform_token_refresh
                result = await perform_token_refresh(refresh_token, get_event_bus()._redis)
                if result is None:
                    await ws.send_json({"type": "error", "detail": "Invalid refresh token"})
                    continue
                await ws.send_json({
                    "type": "token.refreshed",
                    "access_token": result["access_token"],
                    "expires_in": result["expires_in"],
                })

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        expiry_task.cancel()
        await manager.disconnect(user_id, ws)
```

- [ ] **Step 4: Run tests to confirm they still fail (router not wired into app yet)**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_router.py -v 2>&1 | tail -10
```

Expected: still failing — `/ws` not reachable yet

- [ ] **Step 5: Commit router file alone**

```bash
git add backend/ws/router.py
git commit -m "Add WebSocket router with JWT auth, ping/pong, reconnect replay and token refresh"
```

---

## Task 5: Wire main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update `backend/main.py`**

Replace the entire file with:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.user import router as user_router, init_indexes
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from backend.ws.router import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await init_indexes(get_db())
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: Run WS router tests**

```bash
docker compose exec backend python -m pytest ../tests/ws/test_router.py -v 2>&1 | tail -20
```

Expected: all 6 tests PASS

- [ ] **Step 3: Verify existing tests still pass**

```bash
docker compose exec backend python -m pytest ../tests/ -v --ignore=../tests/ws/test_event_bus.py 2>&1 | tail -20
```

Expected: all existing tests PASS (event_bus tests are excluded because they don't need the full app)

- [ ] **Step 4: Run full test suite**

```bash
docker compose exec backend python -m pytest ../tests/ -v 2>&1 | tail -30
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "Wire ConnectionManager and EventBus into app lifespan, include WS router"
```

---

## Task 6: Expose Token Refresh in User Module + Wire Handlers

**Files:**
- Modify: `backend/modules/user/__init__.py`
- Modify: `backend/modules/user/_handlers.py`

- [ ] **Step 1: Add `perform_token_refresh` to user module public API**

Open `backend/modules/user/__init__.py` and replace with:

```python
"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from backend.modules.user._audit import AuditRepository
from backend.modules.user._auth import (
    create_access_token,
    generate_refresh_token,
    generate_session_id,
)
from backend.modules.user._handlers import router
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from backend.config import settings
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for user module collections."""
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()


async def perform_token_refresh(refresh_token: str, redis) -> dict | None:
    """Rotate a refresh token and return new token data, or None if invalid."""
    store = RefreshTokenStore(redis)
    data = await store.consume(refresh_token)
    if data is None:
        return None

    repo = UserRepository(get_db())
    user = await repo.find_by_id(data["user_id"])
    if not user or not user["is_active"]:
        return None

    session_id = data["session_id"]
    access_token = create_access_token(
        user_id=user["_id"],
        role=user["role"],
        session_id=session_id,
        must_change_password=user["must_change_password"],
    )
    new_refresh_token = generate_refresh_token()
    await store.store(new_refresh_token, user_id=user["_id"], session_id=session_id)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


__all__ = ["router", "init_indexes", "perform_token_refresh"]
```

- [ ] **Step 2: Add event publishing to `_handlers.py`**

Add `get_event_bus` import at the top of `backend/modules/user/_handlers.py` (after the existing imports):

```python
from backend.ws.event_bus import EventBus, get_event_bus
```

Then update each handler signature to inject `event_bus` and add publish calls after the audit log write. The pattern for every handler is the same:

**`setup` handler** — add parameter and publish:
```python
async def setup(
    body: SetupRequestDto,
    response: Response,
    event_bus: EventBus = Depends(get_event_bus),
):
    # ... existing logic unchanged ...
    # After: await audit.log(...)
    from shared.events.auth import UserCreatedEvent
    from shared.events.audit import AuditLoggedEvent
    from shared.topics import Topics
    await event_bus.publish(
        Topics.USER_CREATED,
        UserCreatedEvent(user_id=doc["_id"], username=doc["username"], role="master_admin", timestamp=doc["created_at"]),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=doc["_id"], action="user.created", resource_type="user", resource_id=doc["_id"], detail={"role": "master_admin", "method": "setup"}),
    )
    return SetupResponseDto(...)
```

**`create_user` handler**:
```python
async def create_user(
    body: CreateUserRequestDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    # ... existing logic unchanged ...
    # After: await audit.log(...)
    from shared.events.auth import UserCreatedEvent
    from shared.events.audit import AuditLoggedEvent
    from shared.topics import Topics
    await event_bus.publish(
        Topics.USER_CREATED,
        UserCreatedEvent(user_id=doc["_id"], username=doc["username"], role=body.role, timestamp=doc["created_at"]),
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.created", resource_type="user", resource_id=doc["_id"], detail={"role": body.role}),
    )
    return CreateUserResponseDto(...)
```

**`update_user` handler**:
```python
async def update_user(
    user_id: str,
    body: UpdateUserRequestDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    # ... existing logic unchanged ...
    # After: await audit.log(...)
    from shared.events.auth import UserUpdatedEvent
    from shared.events.audit import AuditLoggedEvent
    from shared.topics import Topics
    await event_bus.publish(
        Topics.USER_UPDATED,
        UserUpdatedEvent(user_id=user_id, changes=fields, timestamp=updated["updated_at"]),
        target_user_ids=[user_id],
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.updated", resource_type="user", resource_id=user_id, detail={"changes": fields}),
    )
    return UserRepository.to_dto(updated)
```

**`delete_user` handler**:
```python
async def delete_user(
    user_id: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    # ... existing logic unchanged ...
    # After: await audit.log(...)
    from shared.events.auth import UserDeactivatedEvent
    from shared.events.audit import AuditLoggedEvent
    from shared.topics import Topics
    await event_bus.publish(
        Topics.USER_DEACTIVATED,
        UserDeactivatedEvent(user_id=user_id, timestamp=datetime.now(timezone.utc)),
        target_user_ids=[user_id],
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.deactivated", resource_type="user", resource_id=user_id),
    )
    return {"status": "ok"}
```

**`reset_password` handler**:
```python
async def reset_password(
    user_id: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    # ... existing logic unchanged ...
    # After: await audit.log(...)
    from shared.events.auth import UserPasswordResetEvent
    from shared.events.audit import AuditLoggedEvent
    from shared.topics import Topics
    await event_bus.publish(
        Topics.USER_PASSWORD_RESET,
        UserPasswordResetEvent(user_id=user_id, timestamp=datetime.now(timezone.utc)),
        target_user_ids=[user_id],
    )
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=user["sub"], action="user.password_reset", resource_type="user", resource_id=user_id),
    )
    return ResetPasswordResponseDto(...)
```

**`change_password` handler**:
```python
async def change_password(
    body: ChangePasswordRequestDto,
    response: Response,
    user: dict = Depends(get_current_user),
    event_bus: EventBus = Depends(get_event_bus),
):
    # ... existing logic unchanged ...
    # After: await audit.log(...)
    from shared.events.audit import AuditLoggedEvent
    from shared.topics import Topics
    await event_bus.publish(
        Topics.AUDIT_LOGGED,
        AuditLoggedEvent(actor_id=doc["_id"], action="user.password_changed", resource_type="user", resource_id=doc["_id"]),
    )
    return TokenResponseDto(...)
```

Note: `login`, `refresh`, and `logout` handlers do NOT publish events — they are not state changes that other clients need to observe.

- [ ] **Step 3: Add missing `datetime` import to `_handlers.py` if not already present**

Check the top of `_handlers.py`. If `datetime` and `timezone` are not imported, add:
```python
from datetime import datetime, timezone
```

- [ ] **Step 4: Run the full test suite**

```bash
docker compose exec backend python -m pytest ../tests/ -v 2>&1 | tail -30
```

Expected: all tests PASS

- [ ] **Step 5: Smoke test the running container**

```bash
docker compose restart backend
sleep 3
curl -s http://localhost:8000/api/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 6: Commit**

```bash
git add backend/modules/user/__init__.py backend/modules/user/_handlers.py
git commit -m "Wire event bus into user handlers — publish user and audit events on every state change"
```

---

## Self-Review Notes

- **Spec coverage:** BaseEvent ✓, AuditLoggedEvent ✓, Topics.AUDIT_LOGGED ✓, ConnectionManager ✓, EventBus with Redis Streams ✓, 24h XTRIM retention ✓, fan-out rules (all topics) ✓, audit fan-out filtering by actor_id ✓, WS auth (JWT validation, mcp rejection) ✓, reconnect with `since` ✓, ping/pong ✓, token expiry warning ✓, token refresh over WS ✓, `perform_token_refresh` in user public API ✓, handler wiring ✓.
- **No placeholders:** All steps contain actual code.
- **Type consistency:** `ConnectionManager` methods used in EventBus (`broadcast_to_roles`, `send_to_users`, `send_to_user`, `user_ids_by_role`) match what is defined in Task 2. `get_manager()` / `get_event_bus()` / `set_manager()` / `set_event_bus()` are consistent throughout.
