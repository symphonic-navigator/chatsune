# WebSocket Infrastructure & Event Bus — Design Spec

**Date:** 2026-04-03
**Scope:** WebSocket connection management, in-process event bus, Redis Streams persistence, fan-out for user and audit events
**Phase:** 1 (foundation)

---

## 1. Architecture Overview

Three new components under `backend/ws/`, plus additions to `shared/`:

```
backend/ws/
  __init__.py
  manager.py      ← WebSocket connections (user_id → set[WebSocket])
  router.py       ← WS endpoint, auth handshake, reconnect, token refresh
  event_bus.py    ← publish() → Redis Stream + in-memory fan-out

shared/events/
  base.py         ← BaseEvent envelope
  audit.py        ← AuditLoggedEvent (new)

shared/topics.py  ← Topics.AUDIT_LOGGED added
```

**Event flow:**
```
Handler (e.g. create_user)
  → event_bus.publish(Topics.USER_CREATED, event, scope="global", target_user_ids=[...])
    → Redis XADD "events:global"  (Stream ID becomes the sequence)
    → XTRIM "events:global" MINID <now - 24h>
    → fan-out to connected WebSockets (admins + affected user)
```

Existing handlers in `backend/modules/user/_handlers.py` are not restructured — they receive `event_bus` as a FastAPI dependency and call `await event_bus.publish(...)` at the end of each operation.

The `EventBus` is instantiated once in `main.py` and injected via FastAPI dependency.

---

## 2. BaseEvent Envelope

```python
# shared/events/base.py

class BaseEvent(BaseModel):
    id: str            # UUID4
    type: str          # Topics constant
    sequence: str      # Redis Stream ID, e.g. "1735000000000-0"
    scope: str         # "global" for user management events in Phase 1
    correlation_id: str
    timestamp: datetime
    payload: dict
```

**sequence** uses the Redis Stream ID directly — it is monotonically increasing and globally ordered within a stream, making it directly usable as the `since` parameter for XRANGE reconnect queries. No separate Redis counter needed.

**scope** is `"global"` for all user management and audit events in Phase 1. Future modules (chat, persona) will use scopes like `"persona:abc123"`.

---

## 3. Event Bus

```python
# backend/ws/event_bus.py

class EventBus:
    def __init__(self, redis, manager: ConnectionManager) -> None: ...

    async def publish(
        self,
        topic: str,
        event: BaseModel,
        scope: str = "global",
        target_user_ids: list[str] | None = None,
    ) -> None:
        # 1. Wrap in BaseEvent envelope (assign UUID, timestamp, sequence placeholder)
        # 2. XADD to "events:{scope}" → get Stream ID
        # 3. Set sequence = Stream ID, update envelope
        # 4. XTRIM "events:{scope}" MINID <now_ms - 86_400_000>
        # 5. Fan-out via ConnectionManager
```

### Fan-out Rules

| Topic | Admins / Master-Admin | Affected User |
|---|---|---|
| `user.created` | all connected | — |
| `user.updated` | all connected | yes (`target_user_ids`) |
| `user.deactivated` | all connected | yes (`target_user_ids`) |
| `user.password_reset` | all connected | yes (`target_user_ids`) |
| `audit.logged` | master_admin: all; admin: own entries only | — |

`target_user_ids` is passed by the handler (e.g. the ID of the affected user). The event bus applies fan-out logic based on the topic and the caller-supplied target list.

For `audit.logged`, the event payload includes `actor_id`. The event bus sends the event to master_admin connections unconditionally, and to admin connections only when `actor_id == their user_id`.

---

## 4. Connection Manager

```python
# backend/ws/manager.py

class ConnectionManager:
    _connections: dict[str, set[WebSocket]]  # user_id → active connections
    _user_roles: dict[str, str]              # user_id → role (set on connect)

    async def connect(self, user_id: str, role: str, ws: WebSocket) -> None
    async def disconnect(self, user_id: str, ws: WebSocket) -> None
    async def send_to_user(self, user_id: str, event: dict) -> None
    async def send_to_users(self, user_ids: list[str], event: dict) -> None
    async def broadcast_to_roles(self, roles: list[str], event: dict) -> None
```

Multiple sessions per user are supported — `set[WebSocket]` per `user_id`. The event bus calls `broadcast_to_roles` for admin fan-out and `send_to_users` for affected-user delivery. The manager holds the role mapping so the event bus never queries the database during fan-out.

---

## 5. WebSocket Endpoint & Auth Handshake

**URL:** `ws://host/ws?token=<access_jwt>&since=<last_stream_id>`

`since` is optional — omit on first connect.

### Connect Flow

1. Validate JWT from `token` query parameter. Invalid → close with code `4001`.
2. If token has `mcp: true` (must change password) → close with code `4003`.
3. Register connection in `ConnectionManager` with `user_id` and `role`.
4. If `since` provided: `XRANGE events:global (since +` → send all missed events before entering normal operation.
5. Schedule token expiry warning: `asyncio.sleep` until 2 minutes before `exp`, then send `{"type": "token.expiring_soon"}`.
6. Enter receive loop.

### Client → Server Messages

```json
{"type": "ping"}
→ {"type": "pong"}

{"type": "token.refresh"}
→ Server reads refresh_token cookie from the original WS handshake request,
  rotates token pair (same logic as POST /api/auth/refresh),
  responds: {"type": "token.refreshed", "access_token": "...", "expires_in": 900}
```

### Disconnect

`ConnectionManager.disconnect(user_id, ws)` is called in a `finally` block — cleans up the connection from both `_connections` and `_user_roles` (only if no other sessions remain for that user).

### WebSocket Close Codes

| Code | Meaning |
|---|---|
| 4001 | Invalid or expired token |
| 4003 | Must change password before connecting |

---

## 6. Additions to Shared Contracts

### `shared/events/base.py` (new)
- `BaseEvent`

### `shared/events/audit.py` (new)
- `AuditLoggedEvent` — wraps `AuditLogEntryDto` as payload

### `shared/topics.py` (updated)
- `Topics.AUDIT_LOGGED = "audit.logged"`

---

## 7. Wiring User Handlers

Each handler in `backend/modules/user/_handlers.py` gets `event_bus: EventBus = Depends(get_event_bus)` added to its signature. After the audit log write, it calls:

```python
await event_bus.publish(
    Topics.USER_CREATED,
    UserCreatedEvent(...),
    target_user_ids=[doc["_id"]],
)
```

The audit log write itself also publishes:

```python
await event_bus.publish(
    Topics.AUDIT_LOGGED,
    AuditLoggedEvent(...),
)
```

This keeps all event publishing in `_handlers.py` — `_audit.py` and `_repository.py` stay free of event bus concerns.

---

## 8. What Is Not in Scope

- Frontend WebSocket client (separate feature)
- Redis Streams consumer groups (not needed for single-instance monolith)
- Horizontal scaling / Redis Pub/Sub fan-out across instances
- Chat, Persona, LLM events (future modules)
