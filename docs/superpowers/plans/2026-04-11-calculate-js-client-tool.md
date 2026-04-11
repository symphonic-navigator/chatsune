# `calculate_js` Client-Side Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `calculate_js`, a sandboxed JavaScript evaluator running in a browser Web Worker that the LLM can call as a programmable calculator, and in doing so build the full client-side tool forwarding infrastructure (server-side await, targeted per-connection event delivery, disconnect handling).

**Architecture:** Server-side inference loop transparently routes `ToolGroup.side == "client"` tool calls through a new `ClientToolDispatcher` that publishes a `ChatClientToolDispatchEvent` targeted at the originating WebSocket connection and awaits a `chat.client_tool.result` message from the browser. The browser executes the snippet in a short-lived Web Worker with dangerous globals stripped, captures `console.log` output into a 4 KB buffer, and sends back `{stdout, error}`. All failure paths converge on synthetic error results fed back into the tool loop.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + asyncio (backend), TypeScript + React + Vite + Web Worker API (frontend), MongoDB 7.0, Redis, `pytest` for backend tests, Vitest for frontend tests, `uv` and `pnpm` as package managers.

**Spec:** `docs/superpowers/specs/2026-04-11-calculate-js-client-tool-design.md` (commit `3ac632e`).

---

## File Map

**New files:**
- `backend/modules/tools/_client_dispatcher.py` — `ClientToolDispatcher` class
- `frontend/src/features/code-execution/sandbox.worker.ts` — Web Worker bootstrap
- `frontend/src/features/code-execution/sandboxHost.ts` — Worker lifecycle and timeout wrapper
- `frontend/src/features/code-execution/clientToolHandler.ts` — dispatch event subscriber
- `tests/modules/tools/test_client_dispatcher.py` — backend unit tests for the dispatcher
- `tests/modules/tools/test_execute_tool_client_branch.py` — unit tests for the `execute_tool` client branch
- `tests/ws/test_event_bus_targeted_fanout.py` — unit tests for the new fanout parameter
- `frontend/src/features/code-execution/__tests__/sandbox.worker.test.ts` — Vitest tests for the worker
- `frontend/src/features/code-execution/__tests__/sandboxHost.test.ts` — Vitest tests for the host
- `frontend/src/features/code-execution/__tests__/clientToolHandler.test.ts` — Vitest tests for the handler

**Modified files:**
- `shared/topics.py` — new constant `CHAT_CLIENT_TOOL_DISPATCH`
- `shared/events/chat.py` — new `ChatClientToolDispatchEvent`
- `shared/dtos/tools.py` — new `ClientToolResultPayload` and `ClientToolResultDto`
- `backend/ws/manager.py` — connection_id bookkeeping, `send_to_connection` method
- `backend/ws/event_bus.py` — `target_connection_id` parameter in `publish()`, new fanout entry
- `backend/ws/router.py` — assign connection_id, send hello, dispatch `chat.client_tool.result`, pass connection_id to chat handlers
- `backend/modules/chat/_handlers_ws.py` — accept `connection_id` and thread through
- `backend/modules/chat/_orchestrator.py` — accept `connection_id`, pass to `_make_tool_executor`, extend executor closure
- `backend/modules/chat/_inference.py` — pass `tool_call_id` to executor
- `backend/modules/tools/__init__.py` — extended `execute_tool` signature, `get_client_dispatcher()` export
- `backend/modules/tools/_registry.py` — register `code_execution` group
- `frontend/src/core/websocket/connection.ts` — handle `ws.hello`, store connection_id, expose getter
- `frontend/src/core/store/eventStore.ts` — add `connectionId` state slot (or a new dedicated slot)
- `frontend/src/App.tsx` — register `clientToolHandler` at app startup

---

## Task Sequencing

Tasks are ordered so each builds on the previous. Contracts first (Tasks 1–3), then the targeted-fanout infrastructure (4–6), then the dispatcher and `execute_tool` branch (7–8), then the tool group (9), then the end-to-end server wiring (10–12), then the frontend (13–17), and finally verification (18).

Dependencies between tasks are noted explicitly. Each task commits independently and is runnable in isolation.

---

## Task 1: Shared topic constant + fanout entry

**Files:**
- Modify: `shared/topics.py` — add `CHAT_CLIENT_TOOL_DISPATCH`
- Modify: `backend/ws/event_bus.py` — add `_FANOUT` entry + `_SKIP_PERSISTENCE` membership

The new topic is one of the high-frequency ephemeral events (like `CHAT_TOOL_CALL_STARTED`), so it joins `_SKIP_PERSISTENCE`. Skipping Redis persistence is correct: a stale dispatch event on reconnect must never replay, because the corresponding future has long since timed out.

- [ ] **Step 1: Add the topic constant**

Open `shared/topics.py`. Find the `Topics` class (or namespace; inspect to confirm the style). Add:

```python
CHAT_CLIENT_TOOL_DISPATCH = "chat.client_tool.dispatch"
```

Place it near the other `CHAT_TOOL_CALL_*` entries.

- [ ] **Step 2: Register in `_FANOUT`**

Open `backend/ws/event_bus.py`. Find the `_FANOUT` dict. Add near the `# Tool call progress — target user only` block:

```python
    Topics.CHAT_CLIENT_TOOL_DISPATCH: ([], True),
```

- [ ] **Step 3: Register in `_SKIP_PERSISTENCE`**

In the same file, find `_SKIP_PERSISTENCE: set[str]`. Add:

```python
    Topics.CHAT_CLIENT_TOOL_DISPATCH,
```

- [ ] **Step 4: Verify the module compiles**

Run: `uv run python -m py_compile backend/ws/event_bus.py shared/topics.py`
Expected: no output, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py backend/ws/event_bus.py
git commit -m "Add CHAT_CLIENT_TOOL_DISPATCH topic and fanout entry"
```

---

## Task 2: `ChatClientToolDispatchEvent`

**Files:**
- Modify: `shared/events/chat.py`

The event uses Pydantic v2 (per CLAUDE.md). It carries `target_connection_id` as a first-class field because the event bus fanout (Task 6) reads it directly from the publish kwargs, but the client may also want it for debugging display, so it lives in the payload too.

- [ ] **Step 1: Add the event class**

Open `shared/events/chat.py`. Import `BaseModel` if not already imported. Add the class near the other `ChatToolCall*` events:

```python
class ChatClientToolDispatchEvent(BaseModel):
    """Server → client: please execute this tool call and reply with chat.client_tool.result."""
    type: str = "chat.client_tool.dispatch"
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict
    timeout_ms: int
    target_connection_id: str
```

- [ ] **Step 2: Verify the module compiles**

Run: `uv run python -m py_compile shared/events/chat.py`
Expected: exit code 0, no output.

- [ ] **Step 3: Smoke-test instantiation**

Run:
```bash
uv run python -c "from shared.events.chat import ChatClientToolDispatchEvent; print(ChatClientToolDispatchEvent(session_id='s', tool_call_id='t', tool_name='calculate_js', arguments={'code':'console.log(1)'}, timeout_ms=5000, target_connection_id='c').model_dump_json())"
```
Expected: a JSON string containing all fields.

- [ ] **Step 4: Commit**

```bash
git add shared/events/chat.py
git commit -m "Add ChatClientToolDispatchEvent for client-side tool forwarding"
```

---

## Task 3: Client-tool-result DTOs

**Files:**
- Modify: `shared/dtos/tools.py`

These DTOs validate the inbound `chat.client_tool.result` WebSocket message (Task 11).

- [ ] **Step 1: Add the DTOs**

Open `shared/dtos/tools.py`. Add at the bottom (keep the `ToolGroupDto` class intact):

```python
class ClientToolResultPayload(BaseModel):
    """The shape of the `result` field in a chat.client_tool.result WS message."""
    stdout: str
    error: str | None


class ClientToolResultDto(BaseModel):
    """Validates inbound chat.client_tool.result WebSocket messages."""
    tool_call_id: str
    result: ClientToolResultPayload
```

Ensure `BaseModel` is already imported at the top of the file.

- [ ] **Step 2: Verify compilation**

Run: `uv run python -m py_compile shared/dtos/tools.py`
Expected: exit code 0.

- [ ] **Step 3: Smoke-test validation**

Run:
```bash
uv run python -c "
from shared.dtos.tools import ClientToolResultDto
ok = ClientToolResultDto.model_validate({'tool_call_id': 'abc', 'result': {'stdout': '3', 'error': None}})
print(ok)
try:
    ClientToolResultDto.model_validate({'tool_call_id': 'abc'})
except Exception as e:
    print('validation error as expected:', type(e).__name__)
"
```
Expected: first print shows a populated model, second prints `validation error as expected: ValidationError`.

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/tools.py
git commit -m "Add ClientToolResultDto for inbound client tool results"
```

---

## Task 4: `ConnectionManager` connection-id bookkeeping

**Files:**
- Modify: `backend/ws/manager.py`
- Test: `tests/ws/test_connection_manager_connection_id.py` (new file)

`ConnectionManager` currently stores `dict[str, set[WebSocket]]`. We replace the inner structure with `dict[str, dict[str, WebSocket]]` so that each connection has a stable id, and add a `send_to_connection(user_id, connection_id, event)` method. All existing call sites (`send_to_user`, `send_to_users`, `broadcast_to_roles`, etc.) must keep working.

- [ ] **Step 1: Write the failing test**

Create `tests/ws/test_connection_manager_connection_id.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ws.manager import ConnectionManager


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_connect_assigns_connection_id():
    mgr = ConnectionManager()
    ws = _FakeWs()
    conn_id = await mgr.connect("user-a", "user", ws)  # returns the assigned id
    assert isinstance(conn_id, str) and len(conn_id) >= 8
    assert mgr.has_connections("user-a")


@pytest.mark.asyncio
async def test_two_connections_get_distinct_ids():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    a = await mgr.connect("user-a", "user", ws_a)
    b = await mgr.connect("user-a", "user", ws_b)
    assert a != b


@pytest.mark.asyncio
async def test_send_to_connection_reaches_only_target():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    a = await mgr.connect("user-a", "user", ws_a)
    b = await mgr.connect("user-a", "user", ws_b)

    await mgr.send_to_connection("user-a", a, {"type": "hello"})

    assert ws_a.sent == [{"type": "hello"}]
    assert ws_b.sent == []


@pytest.mark.asyncio
async def test_send_to_connection_unknown_id_is_silent_noop():
    mgr = ConnectionManager()
    ws = _FakeWs()
    await mgr.connect("user-a", "user", ws)
    # Must not raise — delivery is best-effort.
    await mgr.send_to_connection("user-a", "no-such-id", {"type": "hello"})
    assert ws.sent == []


@pytest.mark.asyncio
async def test_disconnect_removes_only_the_matching_connection():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    a = await mgr.connect("user-a", "user", ws_a)
    b = await mgr.connect("user-a", "user", ws_b)

    await mgr.disconnect("user-a", ws_a)

    # User still has one connection — ws_b
    assert mgr.has_connections("user-a")
    await mgr.send_to_connection("user-a", b, {"type": "still-here"})
    assert ws_b.sent == [{"type": "still-here"}]


@pytest.mark.asyncio
async def test_send_to_user_still_broadcasts_to_all_connections():
    mgr = ConnectionManager()
    ws_a, ws_b = _FakeWs(), _FakeWs()
    await mgr.connect("user-a", "user", ws_a)
    await mgr.connect("user-a", "user", ws_b)
    await mgr.send_to_user("user-a", {"type": "broadcast"})
    assert ws_a.sent == [{"type": "broadcast"}]
    assert ws_b.sent == [{"type": "broadcast"}]
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/ws/test_connection_manager_connection_id.py -v`
Expected: failures — `ConnectionManager.connect` doesn't return anything, `send_to_connection` doesn't exist.

- [ ] **Step 3: Refactor `ConnectionManager`**

Open `backend/ws/manager.py`. Replace the class body with:

```python
import asyncio
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

_manager: "ConnectionManager | None" = None


class ConnectionManager:
    def __init__(self) -> None:
        # user_id -> connection_id -> WebSocket
        self._connections: dict[str, dict[str, WebSocket]] = {}
        self._user_roles: dict[str, str] = {}

    async def connect(self, user_id: str, role: str, ws: WebSocket) -> str:
        """Register a new WebSocket and return its assigned connection id."""
        connection_id = str(uuid4())
        if user_id not in self._connections:
            self._connections[user_id] = {}
        self._connections[user_id][connection_id] = ws
        self._user_roles[user_id] = role
        return connection_id

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(user_id)
        if not conns:
            return
        dead_ids = [cid for cid, w in conns.items() if w is ws]
        for cid in dead_ids:
            del conns[cid]
        if not conns:
            del self._connections[user_id]
            del self._user_roles[user_id]

    def _iter_sockets(self, user_id: str) -> list[WebSocket]:
        return list(self._connections.get(user_id, {}).values())

    async def _send_ws_safe(self, user_id: str, ws: WebSocket, event: dict) -> None:
        try:
            await ws.send_json(event)
        except WebSocketDisconnect:
            await self.disconnect(user_id, ws)
        except Exception:
            await self.disconnect(user_id, ws)

    async def send_to_user(self, user_id: str, event: dict) -> None:
        sockets = self._iter_sockets(user_id)
        if not sockets:
            return
        await asyncio.gather(
            *(self._send_ws_safe(user_id, ws, event) for ws in sockets),
            return_exceptions=True,
        )

    async def send_to_users(self, user_ids: list[str], event: dict) -> None:
        for user_id in user_ids:
            await self.send_to_user(user_id, event)

    async def send_to_connection(
        self, user_id: str, connection_id: str, event: dict,
    ) -> None:
        """Deliver an event to exactly one WebSocket, identified by connection id.

        Best-effort: silent no-op if the connection is unknown (already
        disconnected, wrong user, or never existed).
        """
        ws = self._connections.get(user_id, {}).get(connection_id)
        if ws is None:
            return
        await self._send_ws_safe(user_id, ws, event)

    async def broadcast_to_roles(self, roles: list[str], event: dict) -> None:
        for user_id, role in list(self._user_roles.items()):
            if role in roles:
                await self.send_to_user(user_id, event)

    def user_ids_by_role(self, role: str) -> list[str]:
        return [uid for uid, r in self._user_roles.items() if r == role]

    def has_connections(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))

    def connection_ids_for_user(self, user_id: str) -> list[str]:
        """Return the list of connection ids currently held for the user."""
        return list(self._connections.get(user_id, {}).keys())

    def update_role(self, user_id: str, role: str) -> None:
        if user_id in self._connections:
            self._user_roles[user_id] = role

    async def broadcast_to_all(self, event: dict) -> None:
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, event)


def set_manager(manager: ConnectionManager) -> None:
    global _manager
    _manager = manager


def get_manager() -> ConnectionManager:
    if _manager is None:
        raise RuntimeError("ConnectionManager not initialised")
    return _manager
```

Note: `connection_ids_for_user` is added in preparation for the disconnect hook in Task 12.

- [ ] **Step 4: Run the new tests — verify they pass**

Run: `uv run pytest tests/ws/test_connection_manager_connection_id.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Check that `connect()` callers still work**

The signature change is backwards-compatible for existing callers that ignored the return value — `await manager.connect(...)` just now returns a string they may discard. Check the only existing caller (the WS router) compiles:

Run: `uv run python -m py_compile backend/ws/router.py`
Expected: exit code 0.

- [ ] **Step 6: Run the existing test suite for the ws module**

Run: `uv run pytest tests/ws -v`
Expected: all tests pass. If any test mocks `ConnectionManager._connections` directly, fix it to match the new structure.

- [ ] **Step 7: Commit**

```bash
git add backend/ws/manager.py tests/ws/test_connection_manager_connection_id.py
git commit -m "Track per-connection ids in ConnectionManager, add send_to_connection"
```

---

## Task 5: WebSocket router — assign connection_id and send hello

**Files:**
- Modify: `backend/ws/router.py`

The router now captures the `connection_id` returned by `manager.connect(...)` and immediately sends a `ws.hello` message containing it. It also adds a placeholder branch for the new inbound `chat.client_tool.result` message type — just log and drop for now, so the message is recognised as valid. Task 11 replaces this placeholder with the real handler.

**Critically, this task does NOT pass `connection_id` into the chat handler calls.** Those call-site changes happen in Task 10, atomically with the handler signature changes, to avoid a broken intermediate runtime state.

- [ ] **Step 1: Capture connection_id and send hello**

In `backend/ws/router.py`, replace the line
```python
await manager.connect(user_id, role, ws)
```
with:
```python
connection_id = await manager.connect(user_id, role, ws)
try:
    await ws.send_json({"type": "ws.hello", "connection_id": connection_id})
except Exception:
    _log.warning("Failed to send ws.hello to user %s", user_id)
```

- [ ] **Step 2: Add placeholder branch for chat.client_tool.result**

Find the `while True` message loop. After the existing `chat.incognito.send` branch, add:

```python
elif msg_type == "chat.client_tool.result":
    # Handled fully in Task 11 — for now, log and drop so the
    # message type is recognised.
    _log.debug(
        "chat.client_tool.result received (handler not yet wired) "
        "user=%s connection=%s",
        user_id, connection_id,
    )
```

**Do not modify any other branch in this task.** Chat handler call sites stay as they are — those change in Task 10.

- [ ] **Step 3: Compile check**

Run: `uv run python -m py_compile backend/ws/router.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/ws/router.py
git commit -m "Assign connection_id on WS accept, send ws.hello, recognise client_tool.result"
```

---

## Task 6: Event bus — `target_connection_id` parameter

**Files:**
- Modify: `backend/ws/event_bus.py`
- Test: `tests/ws/test_event_bus_targeted_fanout.py` (new file)

`publish()` gains a new optional `target_connection_id: str | None = None`. When provided, the fanout routes to `manager.send_to_connection(user_id, target_connection_id, event_dict)` for **only that** user/connection pair, and **skips** the normal `send_to_users` broadcast for the target list. Broadcast-to-roles still fires as before. When `target_connection_id` is `None`, behaviour is unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/ws/test_event_bus_targeted_fanout.py`:

```python
import pytest
from unittest.mock import ANY, AsyncMock

from backend.ws.event_bus import EventBus
from shared.topics import Topics

pytestmark = pytest.mark.asyncio


def _make_bus() -> tuple[EventBus, AsyncMock]:
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1-0")
    manager = AsyncMock()
    bus = EventBus(redis, manager)
    return bus, manager


async def test_target_connection_id_routes_to_single_connection():
    bus, manager = _make_bus()

    from shared.events.chat import ChatClientToolDispatchEvent
    event = ChatClientToolDispatchEvent(
        session_id="s1",
        tool_call_id="t1",
        tool_name="calculate_js",
        arguments={"code": "console.log(1)"},
        timeout_ms=5000,
        target_connection_id="conn-42",
    )

    await bus.publish(
        Topics.CHAT_CLIENT_TOOL_DISPATCH,
        event,
        scope="user:u1",
        target_user_ids=["u1"],
        target_connection_id="conn-42",
    )

    # Exactly one targeted call — to the specific connection.
    manager.send_to_connection.assert_awaited_once()
    args, _ = manager.send_to_connection.call_args
    assert args[0] == "u1"
    assert args[1] == "conn-42"
    # No broadcast-to-user fallback.
    manager.send_to_users.assert_not_awaited()
    # Role broadcast still fires (with empty roles list, so it's a no-op
    # in practice — but the call itself must still happen because every
    # publish goes through broadcast_to_roles).
    manager.broadcast_to_roles.assert_awaited_once_with([], ANY)


async def test_without_target_connection_id_uses_normal_fanout():
    bus, manager = _make_bus()

    from shared.events.chat import ChatToolCallStartedEvent
    from datetime import datetime, timezone

    # Existing topic — must continue to use send_to_users
    event = ChatToolCallStartedEvent(
        correlation_id="c",
        tool_call_id="t1",
        tool_name="web_search",
        arguments={},
        timestamp=datetime.now(timezone.utc),
    )

    await bus.publish(
        Topics.CHAT_TOOL_CALL_STARTED,
        event,
        scope="user:u1",
        target_user_ids=["u1"],
    )

    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)
    manager.send_to_connection.assert_not_awaited()
```

Note: if `ChatToolCallStartedEvent`'s constructor requires different kwargs in the real codebase (e.g. an additional field), adapt the stub minimally. The test's purpose is to verify that passing `target_connection_id` routes differently — the specific event type is replaceable.

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/ws/test_event_bus_targeted_fanout.py -v`
Expected: failures because `publish()` doesn't accept `target_connection_id`.

- [ ] **Step 3: Extend `publish()` and `_fan_out()`**

In `backend/ws/event_bus.py`:

Change the `publish` signature:

```python
async def publish(
    self,
    topic: str,
    event: BaseModel,
    scope: str = "global",
    target_user_ids: list[str] | None = None,
    correlation_id: str | None = None,
    target_connection_id: str | None = None,
) -> None:
```

Pass the new parameter through to `_fan_out`:

```python
await self._fan_out(
    topic,
    envelope.model_dump(mode="json"),
    target_user_ids or [],
    target_connection_id=target_connection_id,
)
```

Update `_fan_out` signature:

```python
async def _fan_out(
    self,
    topic: str,
    event_dict: dict,
    target_user_ids: list[str],
    *,
    target_connection_id: str | None = None,
) -> None:
```

And add the targeted branch **before** the existing `send_to_targets` logic:

```python
roles, send_to_targets = _FANOUT[topic]
# BD-031: broadcasts to ALL connected users with matching roles —
# no resource-level filtering (see comment on _FANOUT).
await self._manager.broadcast_to_roles(roles, event_dict)

if target_connection_id is not None and target_user_ids:
    # Targeted delivery — exactly one (user_id, connection_id) pair.
    # Used by client-side tool dispatch to avoid duplicate execution
    # across multi-tab sessions. The first element of target_user_ids
    # is the owning user; we never deliver to other users even if
    # multiple are listed (targeted delivery is single-recipient).
    await self._manager.send_to_connection(
        target_user_ids[0], target_connection_id, event_dict,
    )
elif send_to_targets and target_user_ids:
    await self._manager.send_to_users(target_user_ids, event_dict)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/ws/test_event_bus_targeted_fanout.py -v`
Expected: both tests pass.

- [ ] **Step 5: Run the full ws test suite for regressions**

Run: `uv run pytest tests/ws -v`
Expected: all pre-existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/ws/event_bus.py tests/ws/test_event_bus_targeted_fanout.py
git commit -m "Add target_connection_id for per-connection event delivery"
```

---

## Task 7: `ClientToolDispatcher` class

**Files:**
- Create: `backend/modules/tools/_client_dispatcher.py`
- Create: `tests/modules/tools/test_client_dispatcher.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/modules/tools/test_client_dispatcher.py`:

```python
import asyncio
import json

import pytest

from backend.modules.tools._client_dispatcher import ClientToolDispatcher

pytestmark = pytest.mark.asyncio


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, topic, event, **kwargs):
        self.published.append({"topic": topic, "event": event, "kwargs": kwargs})


@pytest.fixture
def bus(monkeypatch):
    bus = _FakeEventBus()
    import backend.modules.tools._client_dispatcher as mod
    monkeypatch.setattr(mod, "get_event_bus", lambda: bus)
    return bus


async def test_happy_path(bus):
    dispatcher = ClientToolDispatcher()

    async def simulate_client():
        await asyncio.sleep(0.01)  # let dispatch publish first
        dispatcher.resolve(
            tool_call_id="tc-1",
            received_from_user_id="user-a",
            result_json='{"stdout": "3\\n", "error": null}',
        )

    simulator = asyncio.create_task(simulate_client())
    result = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-1",
        tool_name="calculate_js",
        arguments={"code": "console.log(3)"},
        timeout_ms=1000,
        target_connection_id="conn-1",
    )
    await simulator

    assert result == '{"stdout": "3\\n", "error": null}'
    assert dispatcher._pending == {}
    assert len(bus.published) == 1
    pub = bus.published[0]
    assert pub["topic"] == "chat.client_tool.dispatch"
    assert pub["kwargs"]["target_connection_id"] == "conn-1"


async def test_timeout_returns_synthetic_error(bus):
    dispatcher = ClientToolDispatcher()

    result_json = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-2",
        tool_name="calculate_js",
        arguments={"code": "x"},
        timeout_ms=50,
        target_connection_id="conn-1",
    )
    result = json.loads(result_json)

    assert result == {
        "stdout": "",
        "error": "Tool execution timed out after 50ms",
    }
    assert dispatcher._pending == {}


async def test_resolve_user_mismatch_is_ignored(bus, caplog):
    dispatcher = ClientToolDispatcher()

    async def mismatched_client():
        await asyncio.sleep(0.01)
        dispatcher.resolve(
            tool_call_id="tc-3",
            received_from_user_id="user-b",  # wrong user
            result_json='{"stdout": "evil", "error": null}',
        )
        # then correct user resolves
        await asyncio.sleep(0.01)
        dispatcher.resolve(
            tool_call_id="tc-3",
            received_from_user_id="user-a",
            result_json='{"stdout": "ok", "error": null}',
        )

    task = asyncio.create_task(mismatched_client())
    with caplog.at_level("WARNING"):
        result = await dispatcher.dispatch(
            user_id="user-a",
            session_id="sess-1",
            tool_call_id="tc-3",
            tool_name="calculate_js",
            arguments={"code": "x"},
            timeout_ms=1000,
            target_connection_id="conn-1",
        )
    await task

    assert result == '{"stdout": "ok", "error": null}'
    assert any("user mismatch" in rec.message for rec in caplog.records)


async def test_cancel_for_user_resolves_with_disconnect_error(bus):
    dispatcher = ClientToolDispatcher()

    async def disconnect_soon():
        await asyncio.sleep(0.01)
        dispatcher.cancel_for_user("user-a")

    task = asyncio.create_task(disconnect_soon())
    result_json = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-4",
        tool_name="calculate_js",
        arguments={"code": "x"},
        timeout_ms=1000,
        target_connection_id="conn-1",
    )
    await task
    result = json.loads(result_json)

    assert result == {
        "stdout": "",
        "error": "Client disconnected before tool completed",
    }


async def test_unknown_tool_call_id_resolve_is_silent(bus, caplog):
    dispatcher = ClientToolDispatcher()
    with caplog.at_level("WARNING"):
        dispatcher.resolve(
            tool_call_id="ghost",
            received_from_user_id="user-a",
            result_json='{"stdout": "x", "error": null}',
        )
    assert any("unknown tool_call_id" in rec.message for rec in caplog.records)


async def test_duplicate_resolve_first_wins(bus):
    dispatcher = ClientToolDispatcher()

    async def respond_twice():
        await asyncio.sleep(0.01)
        dispatcher.resolve(
            tool_call_id="tc-5",
            received_from_user_id="user-a",
            result_json='{"stdout": "first", "error": null}',
        )
        dispatcher.resolve(
            tool_call_id="tc-5",
            received_from_user_id="user-a",
            result_json='{"stdout": "second", "error": null}',
        )

    task = asyncio.create_task(respond_twice())
    result = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-5",
        tool_name="calculate_js",
        arguments={"code": "x"},
        timeout_ms=1000,
        target_connection_id="conn-1",
    )
    await task

    assert '"stdout": "first"' in result
```

- [ ] **Step 2: Run the tests — expect import failure**

Run: `uv run pytest tests/modules/tools/test_client_dispatcher.py -v`
Expected: `ImportError` — the module doesn't exist yet.

- [ ] **Step 3: Create the dispatcher module**

Create `backend/modules/tools/_client_dispatcher.py`:

```python
"""Client-side tool call dispatcher.

Forwards tool calls whose ``ToolGroup.side == "client"`` to the originating
browser connection and waits for the result. Every failure path returns a
``{"stdout": "...", "error": "..."}`` JSON string — no exceptions escape.
"""

import asyncio
import json
import logging

from backend.ws.event_bus import get_event_bus
from shared.events.chat import ChatClientToolDispatchEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


class ClientToolDispatcher:
    """Awaits ``chat.client_tool.result`` messages and resolves pending futures."""

    def __init__(self) -> None:
        # tool_call_id -> (user_id, asyncio.Future[str])
        self._pending: dict[str, tuple[str, asyncio.Future[str]]] = {}

    async def dispatch(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        timeout_ms: int,
        target_connection_id: str,
    ) -> str:
        """Publish the dispatch event and await the client's response.

        Returns a JSON string of shape ``{"stdout": "...", "error": null|str}``.
        Never raises.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[tool_call_id] = (user_id, future)

        try:
            await get_event_bus().publish(
                Topics.CHAT_CLIENT_TOOL_DISPATCH,
                ChatClientToolDispatchEvent(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    timeout_ms=timeout_ms,
                    target_connection_id=target_connection_id,
                ),
                scope=f"user:{user_id}",
                target_user_ids=[user_id],
                target_connection_id=target_connection_id,
                correlation_id=tool_call_id,
            )
            return await asyncio.wait_for(future, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            return json.dumps({
                "stdout": "",
                "error": f"Tool execution timed out after {timeout_ms}ms",
            })
        finally:
            self._pending.pop(tool_call_id, None)

    def resolve(
        self,
        *,
        tool_call_id: str,
        received_from_user_id: str,
        result_json: str,
    ) -> None:
        """Resolve a pending future with the given result JSON.

        Silent no-op (with warning) if the id is unknown or the user does
        not match. Double-resolve is silently ignored by the
        ``if not future.done()`` check.
        """
        pending = self._pending.get(tool_call_id)
        if pending is None:
            _log.warning(
                "client_tool_result for unknown tool_call_id=%s from user=%s",
                tool_call_id, received_from_user_id,
            )
            return

        expected_user_id, future = pending
        if expected_user_id != received_from_user_id:
            _log.warning(
                "client_tool_result user mismatch: tool_call_id=%s "
                "expected=%s received=%s (dropped)",
                tool_call_id, expected_user_id, received_from_user_id,
            )
            return

        if not future.done():
            future.set_result(result_json)

    def cancel_for_user(self, user_id: str) -> None:
        """Fail every pending future that belongs to this user.

        Called by the WS disconnect path when the user's last connection
        drops. Produces synthetic disconnect errors so the inference loop
        can complete cleanly.
        """
        for call_id, (uid, future) in list(self._pending.items()):
            if uid == user_id and not future.done():
                future.set_result(json.dumps({
                    "stdout": "",
                    "error": "Client disconnected before tool completed",
                }))
```

- [ ] **Step 4: Run the tests — verify they pass**

Run: `uv run pytest tests/modules/tools/test_client_dispatcher.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_client_dispatcher.py tests/modules/tools/test_client_dispatcher.py
git commit -m "Add ClientToolDispatcher with timeout, disconnect, and mismatch handling"
```

---

## Task 8: Extend `execute_tool` with the client-side branch

**Files:**
- Modify: `backend/modules/tools/__init__.py`
- Test: `tests/modules/tools/test_execute_tool_client_branch.py`

`execute_tool` grows three new keyword arguments — `tool_call_id`, `session_id`, `originating_connection_id` — and a branch that routes `side == "client"` tools through the singleton `ClientToolDispatcher`. Existing callers (server-side tools) go through the old executor path unchanged.

Because `execute_tool`'s signature changes, the existing call site in `backend/modules/chat/_orchestrator.py:126` is about to break. Task 10 fixes that. This task only changes the tools module and leaves the orchestrator as-is, which means the test suite will not pass between this task and Task 10. The explicit cross-task compile check is the last step of Task 10.

- [ ] **Step 1: Write the failing test**

Create `tests/modules/tools/test_execute_tool_client_branch.py`:

```python
import json
from unittest.mock import AsyncMock

import pytest

from backend.modules.tools import execute_tool, get_client_dispatcher

pytestmark = pytest.mark.asyncio


async def test_client_side_tool_routes_to_dispatcher(monkeypatch):
    fake_dispatcher = AsyncMock()
    fake_dispatcher.dispatch = AsyncMock(return_value='{"stdout": "ok", "error": null}')

    import backend.modules.tools as tools_mod
    monkeypatch.setattr(
        tools_mod, "_client_dispatcher", fake_dispatcher, raising=False,
    )
    monkeypatch.setattr(
        tools_mod, "get_client_dispatcher", lambda: fake_dispatcher,
    )

    result = await execute_tool(
        user_id="user-a",
        tool_name="calculate_js",
        arguments_json='{"code": "console.log(1)"}',
        tool_call_id="tc-1",
        session_id="sess-1",
        originating_connection_id="conn-1",
    )

    assert result == '{"stdout": "ok", "error": null}'
    fake_dispatcher.dispatch.assert_awaited_once()
    kwargs = fake_dispatcher.dispatch.await_args.kwargs
    assert kwargs["tool_call_id"] == "tc-1"
    assert kwargs["tool_name"] == "calculate_js"
    assert kwargs["arguments"] == {"code": "console.log(1)"}
    assert kwargs["target_connection_id"] == "conn-1"
    assert kwargs["timeout_ms"] == 5000


async def test_server_side_tool_still_uses_executor(monkeypatch):
    # web_search is a server-side tool; its executor must still be called.
    from backend.modules.tools._executors import WebSearchExecutor

    mock_execute = AsyncMock(return_value='[{"title":"hi"}]')
    monkeypatch.setattr(WebSearchExecutor, "execute", mock_execute)

    result = await execute_tool(
        user_id="user-a",
        tool_name="web_search",
        arguments_json='{"query": "hi"}',
        tool_call_id="tc-2",
        session_id="sess-1",
        originating_connection_id="conn-1",
    )

    assert result == '[{"title":"hi"}]'
    mock_execute.assert_awaited_once()
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/modules/tools/test_execute_tool_client_branch.py -v`
Expected: failures — `execute_tool` doesn't accept the new kwargs, `get_client_dispatcher` doesn't exist.

- [ ] **Step 3: Extend `backend/modules/tools/__init__.py`**

Open `backend/modules/tools/__init__.py`. Add imports, timeout constants, and singleton:

```python
import asyncio
import json
import logging
from datetime import datetime, timezone

from backend.modules.tools._client_dispatcher import ClientToolDispatcher
from backend.modules.tools._registry import ToolGroup, get_groups
from shared.dtos.inference import ToolDefinition
from shared.dtos.tools import ToolGroupDto

_log = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 5

# Client-tool timeouts: the server-side wait budget is intentionally ~5s
# larger than the client-side Worker budget to absorb network and
# scheduler jitter. See spec §4.
_CLIENT_TOOL_SERVER_TIMEOUT_MS = 10_000
_CLIENT_TOOL_CLIENT_TIMEOUT_MS = 5_000

_client_dispatcher = ClientToolDispatcher()


def get_client_dispatcher() -> ClientToolDispatcher:
    """Return the singleton client-tool dispatcher (for WS router and disconnect hooks)."""
    return _client_dispatcher
```

Extend `execute_tool`:

```python
async def execute_tool(
    user_id: str,
    tool_name: str,
    arguments_json: str,
    *,
    tool_call_id: str,
    session_id: str,
    originating_connection_id: str,
) -> str:
    """Dispatch a tool call to the appropriate executor.

    For server-side tools (``side == "server"``) the registered executor is
    invoked directly. For client-side tools (``side == "client"``) the call
    is forwarded to the originating browser connection via the
    ``ClientToolDispatcher`` and this coroutine awaits the result.

    Always returns a string (JSON-encoded result or error). Raises
    ``ToolNotFoundError`` only if the tool name is unknown.
    """
    arguments = json.loads(arguments_json)

    for group in get_groups().values():
        if tool_name not in group.tool_names:
            continue

        if group.side == "client":
            return await _client_dispatcher.dispatch(
                user_id=user_id,
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                timeout_ms=_CLIENT_TOOL_CLIENT_TIMEOUT_MS,
                target_connection_id=originating_connection_id,
            )

        if group.executor is not None:
            return await group.executor.execute(user_id, tool_name, arguments)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")
```

Wait — there's a subtle but important decision here. The spec uses `_CLIENT_TOOL_CLIENT_TIMEOUT_MS` (5 000 ms) as the value sent to the browser **and** the value used by `asyncio.wait_for` on the server. That's wrong: the server should wait longer than the client. Fix the dispatch call to use a separate server-side timeout. Update:

```python
if group.side == "client":
    return await _client_dispatcher.dispatch(
        user_id=user_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        # The server waits longer than the client so the client's own
        # timeout fires first and returns a structured error instead of
        # the server's less-specific timeout.
        timeout_ms=_CLIENT_TOOL_SERVER_TIMEOUT_MS,
        target_connection_id=originating_connection_id,
    )
```

…and additionally, the client needs to be told its **own** shorter budget. The `ClientToolDispatcher.dispatch` currently uses a single `timeout_ms` for both the `asyncio.wait_for` call and the event payload. Open `backend/modules/tools/_client_dispatcher.py` and split this into two parameters:

Change the dispatch signature:

```python
async def dispatch(
    self,
    *,
    user_id: str,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    arguments: dict,
    server_timeout_ms: int,
    client_timeout_ms: int,
    target_connection_id: str,
) -> str:
```

Inside, publish the event with `client_timeout_ms` in the payload, and await with `server_timeout_ms / 1000`:

```python
await get_event_bus().publish(
    Topics.CHAT_CLIENT_TOOL_DISPATCH,
    ChatClientToolDispatchEvent(
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        timeout_ms=client_timeout_ms,
        target_connection_id=target_connection_id,
    ),
    scope=f"user:{user_id}",
    target_user_ids=[user_id],
    target_connection_id=target_connection_id,
    correlation_id=tool_call_id,
)
return await asyncio.wait_for(future, timeout=server_timeout_ms / 1000)
```

And update the timeout-error message to reference the server-side value:

```python
except asyncio.TimeoutError:
    return json.dumps({
        "stdout": "",
        "error": f"Tool execution timed out after {server_timeout_ms}ms",
    })
```

Update the Task 7 tests that call `dispatch` — replace `timeout_ms=X` with `server_timeout_ms=X, client_timeout_ms=X//2` (or similar). Fix the expected error message in `test_timeout_returns_synthetic_error` to match the new format (`"after 50ms"` stays because `server_timeout_ms=50`).

Update the `execute_tool` client branch accordingly:

```python
if group.side == "client":
    return await _client_dispatcher.dispatch(
        user_id=user_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        server_timeout_ms=_CLIENT_TOOL_SERVER_TIMEOUT_MS,
        client_timeout_ms=_CLIENT_TOOL_CLIENT_TIMEOUT_MS,
        target_connection_id=originating_connection_id,
    )
```

Also update the exported `__all__` to include `get_client_dispatcher`:

```python
__all__ = [
    "get_all_groups",
    "get_active_definitions",
    "execute_tool",
    "get_max_tool_iterations",
    "get_client_dispatcher",
    "ToolNotFoundError",
]
```

- [ ] **Step 4: Update Task 7 tests to use the new dispatcher signature**

Edit `tests/modules/tools/test_client_dispatcher.py`:
- Replace every `timeout_ms=1000` with `server_timeout_ms=1000, client_timeout_ms=500`
- Replace `timeout_ms=50` with `server_timeout_ms=50, client_timeout_ms=25`
- The expected error string stays `"Tool execution timed out after 50ms"` because `server_timeout_ms` is what's reported.

- [ ] **Step 5: Run both test files**

Run: `uv run pytest tests/modules/tools/test_client_dispatcher.py tests/modules/tools/test_execute_tool_client_branch.py -v`
Expected: all tests pass.

- [ ] **Step 6: Compile check across the tool module**

Run: `uv run python -m py_compile backend/modules/tools/__init__.py backend/modules/tools/_client_dispatcher.py`
Expected: exit code 0.

- [ ] **Step 7: Commit**

```bash
git add \
  backend/modules/tools/__init__.py \
  backend/modules/tools/_client_dispatcher.py \
  tests/modules/tools/test_client_dispatcher.py \
  tests/modules/tools/test_execute_tool_client_branch.py
git commit -m "Route side=client tools through ClientToolDispatcher in execute_tool"
```

---

## Task 9: Register `code_execution` ToolGroup

**Files:**
- Modify: `backend/modules/tools/_registry.py`

- [ ] **Step 1: Add the group definition**

Open `backend/modules/tools/_registry.py`. Locate `_build_groups()`. After the `"artefacts"` entry, add:

```python
"code_execution": ToolGroup(
    id="code_execution",
    display_name="Code Execution",
    description=(
        "Run small JavaScript snippets for calculations, string "
        "operations, and JSON handling — executed in a sandboxed Web "
        "Worker in your browser. No network, no DOM, no state between "
        "calls."
    ),
    side="client",
    toggleable=True,
    tool_names=["calculate_js"],
    definitions=[
        ToolDefinition(
            name="calculate_js",
            description=(
                "Execute a short JavaScript snippet for calculations, "
                "string operations, or JSON handling. The snippet runs "
                "in an isolated sandbox with no network or state. Use "
                "console.log(...) to emit results — anything not logged "
                "is invisible to you. Typical uses: arithmetic that "
                "needs exact results, counting characters or substrings, "
                "parsing or reformatting JSON, date arithmetic. Do NOT "
                "use for anything that requires waiting, network access, "
                "or multiple steps across calls."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "A self-contained JavaScript snippet. Must "
                            "emit its result via console.log. Maximum "
                            "runtime is a few seconds; maximum output "
                            "is a few kilobytes."
                        ),
                    },
                },
                "required": ["code"],
            },
        ),
    ],
    executor=None,  # no server-side executor — routed by side=="client"
),
```

- [ ] **Step 2: Verify compilation**

Run: `uv run python -m py_compile backend/modules/tools/_registry.py`
Expected: exit code 0.

- [ ] **Step 3: Smoke-test the registry**

Run:
```bash
uv run python -c "
from backend.modules.tools._registry import get_groups
g = get_groups()
print('code_execution' in g)
ce = g['code_execution']
print(ce.side, ce.tool_names, ce.executor)
"
```
Expected output:
```
True
client ['calculate_js'] None
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/tools/_registry.py
git commit -m "Register code_execution tool group with calculate_js"
```

---

## Task 10: Thread `connection_id` through chat handlers, orchestrator, and router dispatch

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`
- Modify: `backend/modules/chat/_orchestrator.py`
- Modify: `backend/modules/chat/_inference.py`
- Modify: `backend/ws/router.py`

This task closes the signature loop opened by Task 8. It is **atomic**: handler signatures grow a new optional parameter AND the router starts passing it in the same commit. Before this task, `execute_tool` calls from the orchestrator still use the old positional form (they are about to break at import time), and the router still calls handlers without `connection_id`. This task restores full runtime correctness.

The threading path is:
1. `handle_chat_send(user_id, data)` → `handle_chat_send(user_id, data, *, connection_id)` (and the same for `handle_chat_edit`, `handle_chat_regenerate`, `handle_incognito_send`).
2. Each handler forwards `connection_id` to its orchestrator entry point.
3. The orchestrator passes `connection_id` to `_make_tool_executor(session, persona, correlation_id, connection_id)`.
4. The `_make_tool_executor` closure captures `connection_id` and passes it to `execute_tool(..., originating_connection_id=connection_id)`.
5. The inference runner calls the executor closure with `tool_call_id` so the closure can forward it.
6. The router's message loop now passes `connection_id=connection_id` into the four handler dispatch sites.

- [ ] **Step 1: Inspect the current handler signatures**

Run (read-only — use Read tool if you have it, not bash):
```
backend/modules/chat/_handlers_ws.py
backend/modules/chat/_orchestrator.py
```

Locate each of `handle_chat_send`, `handle_chat_edit`, `handle_chat_regenerate`, `handle_incognito_send`. All four need the same change: append `*, connection_id: str | None = None` to their signature, and pass it through to the orchestrator. Use `str | None` (defaulting to `None`) because any non-WS-triggered caller (unlikely but possible in tests) still works.

- [ ] **Step 2: Add `connection_id` to each handler**

For each of the four handlers in `_handlers_ws.py`, change the signature:

```python
async def handle_chat_send(
    user_id: str,
    data: dict,
    *,
    connection_id: str | None = None,
) -> None:
```

Find the orchestrator call inside each handler and pass `connection_id` through. The precise call shape depends on the existing orchestrator entry point — likely something like `await orchestrate_chat_send(user_id, ..., connection_id=connection_id)`. Match the existing parameter style.

Repeat for `handle_chat_edit`, `handle_chat_regenerate`, `handle_incognito_send`.

- [ ] **Step 3: Pass `connection_id` through the orchestrator**

In `backend/modules/chat/_orchestrator.py`, the orchestrator entry points (`orchestrate_chat_send` or equivalent) accept and forward `connection_id`. Change `_make_tool_executor` to accept and capture it:

```python
def _make_tool_executor(
    session: dict,
    persona: dict | None,
    correlation_id: str = "",
    connection_id: str | None = None,
):
    """Wrap execute_tool to inject session context and forward the
    originating WebSocket connection id for client-side tools."""
    persona_lib_ids = (persona or {}).get("knowledge_library_ids", [])
    session_lib_ids = session.get("knowledge_library_ids", [])
    sanitised = session.get("sanitised", False)

    async def _executor(
        user_id: str,
        tool_name: str,
        arguments_json: str,
        *,
        tool_call_id: str,
    ) -> str:
        if tool_name == "knowledge_search":
            args = json.loads(arguments_json)
            args["_persona_library_ids"] = persona_lib_ids
            args["_session_library_ids"] = session_lib_ids
            args["_sanitised"] = sanitised
            args["_session_id"] = session.get("_id", "")
            arguments_json = json.dumps(args)

        artefact_tools = {
            "create_artefact", "update_artefact", "read_artefact", "list_artefacts",
        }
        if tool_name in artefact_tools:
            args = json.loads(arguments_json)
            args["_session_id"] = session.get("_id", "")
            args["_correlation_id"] = correlation_id
            arguments_json = json.dumps(args)

        return await execute_tool(
            user_id,
            tool_name,
            arguments_json,
            tool_call_id=tool_call_id,
            session_id=session.get("_id", ""),
            originating_connection_id=connection_id or "",
        )

    return _executor
```

And at every call site of `_make_tool_executor`, pass `connection_id` through. Search for `_make_tool_executor(` in the orchestrator and update each call.

- [ ] **Step 4: Pass `tool_call_id` through the inference runner**

Open `backend/modules/chat/_inference.py`. Find the executor call on line ~238:

```python
result_str = await tool_executor_fn(
    user_id, tc.name, tc.arguments,
)
```

Change to:

```python
result_str = await tool_executor_fn(
    user_id, tc.name, tc.arguments,
    tool_call_id=tc.id,
)
```

- [ ] **Step 5: Update the router to pass `connection_id` to handler dispatches**

Open `backend/ws/router.py`. Update each of the four handler dispatch sites in the `while True` message loop to include `connection_id=connection_id`:

```python
elif msg_type == "chat.send":
    task = asyncio.create_task(
        handle_chat_send(user_id, data, connection_id=connection_id)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
elif msg_type == "chat.cancel":
    handle_chat_cancel(user_id, data)
elif msg_type == "chat.edit":
    task = asyncio.create_task(
        handle_chat_edit(user_id, data, connection_id=connection_id)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
elif msg_type == "chat.regenerate":
    task = asyncio.create_task(
        handle_chat_regenerate(user_id, data, connection_id=connection_id)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
elif msg_type == "chat.incognito.send":
    task = asyncio.create_task(
        handle_incognito_send(user_id, data, connection_id=connection_id)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
```

`handle_chat_cancel` stays unchanged — it takes neither a `connection_id` nor issues tool calls. The `chat.client_tool.result` placeholder branch added in Task 5 stays as-is (Task 11 replaces it).

- [ ] **Step 6: Run compile check across changed files**

Run:
```bash
uv run python -m py_compile \
  backend/modules/chat/_handlers_ws.py \
  backend/modules/chat/_orchestrator.py \
  backend/modules/chat/_inference.py \
  backend/ws/router.py \
  backend/modules/tools/__init__.py
```
Expected: exit code 0 for all.

- [ ] **Step 7: Run the full chat test suite**

Run: `uv run pytest tests/modules/chat -v`
Expected: all existing chat tests pass. If any test invokes the tool executor or `execute_tool` directly with the old signature, update them to pass the new keyword arguments (`tool_call_id`, `session_id`, `originating_connection_id`).

- [ ] **Step 8: Run the full tools and ws test suites**

Run: `uv run pytest tests/modules/tools tests/ws -v`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add \
  backend/modules/chat/_handlers_ws.py \
  backend/modules/chat/_orchestrator.py \
  backend/modules/chat/_inference.py \
  backend/ws/router.py
git commit -m "Thread connection_id and tool_call_id from router through to execute_tool"
```

---

## Task 11: WS router handler for `chat.client_tool.result`

**Files:**
- Modify: `backend/ws/router.py`

Replace the placeholder drop-and-log branch added in Task 5 with a real handler that validates the payload against `ClientToolResultDto` and calls `get_client_dispatcher().resolve(...)`.

- [ ] **Step 1: Add imports**

At the top of `backend/ws/router.py`, add:

```python
from pydantic import ValidationError

from backend.modules.tools import get_client_dispatcher
from shared.dtos.tools import ClientToolResultDto
```

- [ ] **Step 2: Replace the placeholder branch**

Find the existing placeholder added in Task 5:

```python
elif msg_type == "chat.client_tool.result":
    _log.debug(
        "chat.client_tool.result received (handler not yet wired) "
        "user=%s connection=%s",
        user_id, connection_id,
    )
```

Replace with:

```python
elif msg_type == "chat.client_tool.result":
    try:
        dto = ClientToolResultDto.model_validate(data)
    except ValidationError as e:
        _log.warning(
            "malformed chat.client_tool.result from user=%s connection=%s: %s",
            user_id, connection_id, e,
        )
    else:
        get_client_dispatcher().resolve(
            tool_call_id=dto.tool_call_id,
            received_from_user_id=user_id,
            result_json=dto.result.model_dump_json(),
        )
```

- [ ] **Step 3: Compile check**

Run: `uv run python -m py_compile backend/ws/router.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/ws/router.py
git commit -m "Wire chat.client_tool.result handler to ClientToolDispatcher.resolve"
```

---

## Task 12: Disconnect hook — cancel pending client tool futures

**Files:**
- Modify: `backend/ws/router.py`

When a user's **last** WebSocket drops (i.e. `manager.has_connections(user_id)` becomes false after the grace period), any pending client-tool futures for that user must be failed with a synthetic disconnect error. Hooking in AFTER the 10-second grace period is correct: a flaky reconnect within 10 s should not cancel the tool, for the same reason it doesn't cancel the in-flight inference.

- [ ] **Step 1: Extend `_delayed_disconnect_cleanup`**

Open `backend/ws/router.py`. Find the `_delayed_disconnect_cleanup` inner function near the bottom of `websocket_endpoint`. After the `cancel_all_for_user(user_id)` call and before `trigger_disconnect_extraction(user_id)`, add:

```python
# Fail any pending client-side tool futures for this user.
# Their inference loop has been cancelled above; this just
# ensures the dispatch futures resolve cleanly instead of
# lingering for their 10-second server timeout.
try:
    get_client_dispatcher().cancel_for_user(user_id)
except Exception:
    _log.warning(
        "Failed to cancel pending client tools for user %s",
        user_id, exc_info=True,
    )
```

- [ ] **Step 2: Compile check**

Run: `uv run python -m py_compile backend/ws/router.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/ws/router.py
git commit -m "Cancel pending client tools on disconnect after grace period"
```

---

## Task 13: `sandbox.worker.ts` — the Web Worker bootstrap

**Files:**
- Create: `frontend/src/features/code-execution/sandbox.worker.ts`
- Create: `frontend/src/features/code-execution/__tests__/sandbox.worker.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/code-execution/__tests__/sandbox.worker.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'

// Vitest supports Worker via ?worker or via its own worker stub.
// We import the worker as a module to get its URL-constructed Worker.
async function runCode(code: string, maxOutputBytes = 4096) {
  const worker = new Worker(
    new URL('../sandbox.worker.ts', import.meta.url),
    { type: 'module' },
  )
  const result = await new Promise<{ stdout: string; error: string | null }>((resolve) => {
    worker.addEventListener('message', (ev) => resolve(ev.data))
    worker.postMessage({ code, maxOutputBytes })
  })
  worker.terminate()
  return result
}

describe('sandbox.worker', () => {
  it('runs simple arithmetic via console.log', async () => {
    const r = await runCode('console.log(2 + 2)')
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('4')
  })

  it('counts characters in erdbeere', async () => {
    const r = await runCode("console.log([...'erdbeere'].filter(c => c === 'r').length)")
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('3')
  })

  it('reports exceptions as error strings', async () => {
    const r = await runCode('throw new Error("boom")')
    expect(r.stdout).toBe('')
    expect(r.error).toContain('Error: boom')
  })

  it('blocks fetch by nulling the global', async () => {
    const r = await runCode('fetch("https://evil.example")')
    expect(r.stdout).toBe('')
    // Calling undefined as a function gives TypeError
    expect(r.error).toContain('TypeError')
  })

  it('truncates output beyond the max budget', async () => {
    const r = await runCode(
      'for (let i = 0; i < 10000; i++) console.log("xxxxxxxxxx")',
      256,
    )
    const byteLength = new TextEncoder().encode(r.stdout).length
    expect(byteLength).toBeLessThanOrEqual(256)
    expect(r.stdout).toContain('(output truncated)')
  })

  it('returns the BigInt result for 2^53 + 1', async () => {
    const r = await runCode('console.log((2n ** 53n + 1n).toString())')
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('9007199254740993')
  })
})
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pnpm --filter frontend vitest run src/features/code-execution/__tests__/sandbox.worker.test.ts`
Expected: failure because the worker file does not exist.

- [ ] **Step 3: Create the worker**

Create `frontend/src/features/code-execution/sandbox.worker.ts`:

```typescript
/* sandbox.worker.ts — runs user-supplied JavaScript in a Web Worker
 * with dangerous globals nulled and output captured into a bounded
 * buffer.
 *
 * The worker accepts exactly one request per instance. The host in
 * sandboxHost.ts creates a fresh worker per call and terminates it
 * after the reply — so there is no per-call cleanup to do here.
 */

interface WorkerRequest {
  code: string
  maxOutputBytes: number
}

interface WorkerResponse {
  stdout: string
  error: string | null
}

// Strip dangerous globals BEFORE anything else touches the scope.
// Each assignment is wrapped in try/catch so defineProperty-protected
// globals (should any exist) cannot crash the bootstrap.
const DANGEROUS_GLOBALS = [
  'fetch',
  'XMLHttpRequest',
  'WebSocket',
  'importScripts',
  'setTimeout',
  'setInterval',
  'clearTimeout',
  'clearInterval',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'Worker',
  'SharedWorker',
  'EventSource',
  'BroadcastChannel',
  'indexedDB',
  'caches',
] as const

for (const name of DANGEROUS_GLOBALS) {
  try {
    ;(self as unknown as Record<string, unknown>)[name] = undefined
  } catch {
    // best-effort
  }
}

function safeStringify(value: unknown): string {
  try {
    if (typeof value === 'string') return value
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

self.addEventListener('message', (event: MessageEvent<WorkerRequest>) => {
  const { code, maxOutputBytes } = event.data
  const lines: string[] = []
  let totalBytes = 0
  let truncated = false
  const encoder = new TextEncoder()

  const captureLine = (...args: unknown[]): void => {
    if (truncated) return
    const line = args.map(safeStringify).join(' ')
    const lineBytes = encoder.encode(line + '\n').length
    if (totalBytes + lineBytes > maxOutputBytes) {
      truncated = true
      const remaining = maxOutputBytes - totalBytes
      if (remaining > 0) {
        // Slice by character — inexact for multi-byte but safe. The
        // truncation marker is always appended below.
        lines.push(line.slice(0, remaining))
        totalBytes = maxOutputBytes
      }
      return
    }
    lines.push(line)
    totalBytes += lineBytes
  }

  ;(self as unknown as { console: unknown }).console = {
    log: captureLine,
    error: captureLine,
    warn: captureLine,
    info: captureLine,
    debug: captureLine,
  }

  let error: string | null = null
  try {
    // Indirect eval — runs in the global scope of the worker, not in
    // the scope of this message handler.
    ;(0, eval)(code)
  } catch (e) {
    error = e instanceof Error ? `${e.name}: ${e.message}` : String(e)
  }

  let stdout = lines.join('\n')
  if (truncated) {
    const marker = ' ... (output truncated)'
    const markerBytes = encoder.encode(marker).length
    // Ensure the final string, with the marker, still fits in the cap.
    if (stdout.length + markerBytes > maxOutputBytes) {
      stdout = stdout.slice(0, Math.max(0, maxOutputBytes - markerBytes))
    }
    stdout = stdout + marker
  }

  const response: WorkerResponse = { stdout, error }
  ;(self as unknown as { postMessage: (data: WorkerResponse) => void }).postMessage(
    response,
  )
})
```

- [ ] **Step 4: Run the tests — verify they pass**

Run: `pnpm --filter frontend vitest run src/features/code-execution/__tests__/sandbox.worker.test.ts`
Expected: all 6 tests pass.

If Vitest cannot load the worker via `new Worker(new URL(..., import.meta.url))` in jsdom mode, switch Vitest's environment to `happy-dom` for this file via a `// @vitest-environment happy-dom` comment at the top of the test file, or configure `test.environment: 'happy-dom'` in `vitest.config.ts`. Happy-DOM has better Worker support. If worker construction still fails, fall back to a direct import of the worker file's module code and invoke the exported handler manually — but the real-Worker test is strongly preferred because it catches `eval`-scope bugs that a direct import would miss.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/code-execution/sandbox.worker.ts \
        frontend/src/features/code-execution/__tests__/sandbox.worker.test.ts
git commit -m "Add sandboxed Web Worker bootstrap for calculate_js"
```

---

## Task 14: `sandboxHost.ts` — Worker lifecycle and timeout

**Files:**
- Create: `frontend/src/features/code-execution/sandboxHost.ts`
- Create: `frontend/src/features/code-execution/__tests__/sandboxHost.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/code-execution/__tests__/sandboxHost.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { runSandbox } from '../sandboxHost'

describe('runSandbox', () => {
  it('returns console.log output from successful code', async () => {
    const r = await runSandbox('console.log("hi")', 5000, 4096)
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('hi')
  })

  it('times out hanging code and reports a client-side timeout error', async () => {
    const r = await runSandbox('while (true) {}', 150, 4096)
    expect(r.stdout).toBe('')
    expect(r.error).toMatch(/Client-side timeout after 150ms/)
  })

  it('propagates sandbox exceptions as error strings', async () => {
    const r = await runSandbox('throw new Error("x")', 5000, 4096)
    expect(r.stdout).toBe('')
    expect(r.error).toContain('Error: x')
  })
})
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `pnpm --filter frontend vitest run src/features/code-execution/__tests__/sandboxHost.test.ts`
Expected: failure — `sandboxHost.ts` does not exist.

- [ ] **Step 3: Create the host**

Create `frontend/src/features/code-execution/sandboxHost.ts`:

```typescript
/* sandboxHost.ts — main-thread wrapper around sandbox.worker.ts.
 *
 * Creates a fresh Worker per call and terminates it after the reply.
 * No pooling: Worker creation overhead is tiny compared to the tool
 * round-trip, and a new Worker gives the strongest possible form of
 * state isolation.
 */

export interface SandboxResult {
  stdout: string
  error: string | null
}

export async function runSandbox(
  code: string,
  timeoutMs: number,
  maxOutputBytes: number,
): Promise<SandboxResult> {
  const worker = new Worker(
    new URL('./sandbox.worker.ts', import.meta.url),
    { type: 'module' },
  )

  const result = await new Promise<SandboxResult>((resolve) => {
    let settled = false
    const settle = (value: SandboxResult): void => {
      if (settled) return
      settled = true
      resolve(value)
    }

    const timeoutHandle = setTimeout(() => {
      worker.terminate()
      settle({
        stdout: '',
        error: `Client-side timeout after ${timeoutMs}ms`,
      })
    }, timeoutMs)

    worker.addEventListener('message', (event: MessageEvent<SandboxResult>) => {
      clearTimeout(timeoutHandle)
      settle(event.data)
    })

    worker.addEventListener('error', (event: ErrorEvent) => {
      clearTimeout(timeoutHandle)
      settle({
        stdout: '',
        error: `Sandbox crash: ${event.message || 'unknown error'}`,
      })
    })

    worker.postMessage({ code, maxOutputBytes })
  })

  // Unconditional terminate covers the happy path (terminate() on an
  // already-terminated Worker is a safe no-op).
  worker.terminate()
  return result
}
```

- [ ] **Step 4: Run the tests — verify they pass**

Run: `pnpm --filter frontend vitest run src/features/code-execution/__tests__/sandboxHost.test.ts`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/code-execution/sandboxHost.ts \
        frontend/src/features/code-execution/__tests__/sandboxHost.test.ts
git commit -m "Add sandboxHost with Worker-per-call lifecycle and timeout"
```

---

## Task 15: Frontend connection_id handling in `connection.ts`

**Files:**
- Modify: `frontend/src/core/websocket/connection.ts`
- Modify: `frontend/src/core/store/eventStore.ts` (or wherever connection state lives)

The frontend needs to recognise the new `ws.hello` message, extract the `connection_id`, and store it for later use by the client tool handler. Because `ws.hello` is not an event envelope (it has no `sequence`), it must be intercepted alongside `pong` and `token.expiring_soon` in `socket.onmessage`.

- [ ] **Step 1: Add a connectionId slot to the event store**

Open `frontend/src/core/store/eventStore.ts`. Find the store shape (Zustand, likely). Add `connectionId: string | null` to the state and a `setConnectionId(id: string | null)` action. Initial value: `null`.

Example pattern (adapt to the existing store style):

```typescript
interface EventState {
  // ... existing fields
  connectionId: string | null
  setConnectionId: (id: string | null) => void
}

export const useEventStore = create<EventState>((set) => ({
  // ... existing fields
  connectionId: null,
  setConnectionId: (id) => set({ connectionId: id }),
}))
```

- [ ] **Step 2: Intercept `ws.hello` in `connection.ts`**

Open `frontend/src/core/websocket/connection.ts`. Find the `socket.onmessage` handler. After the existing `data.type === "pong"` and `token.expiring_soon` branches, add:

```typescript
if (data.type === "ws.hello") {
  if (typeof data.connection_id === "string") {
    useEventStore.getState().setConnectionId(data.connection_id)
  }
  return
}
```

Also clear the connection id on disconnect:

```typescript
socket.onclose = (ev) => {
  if (ws !== socket) return
  useEventStore.getState().setStatus("disconnected")
  useEventStore.getState().setConnectionId(null)
  ws = null
  // ... existing code
}
```

- [ ] **Step 3: Smoke-test the build**

Run: `pnpm --filter frontend tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/websocket/connection.ts frontend/src/core/store/eventStore.ts
git commit -m "Receive and store ws.hello connection_id on the frontend"
```

---

## Task 16: `clientToolHandler.ts` — dispatch-event subscriber

**Files:**
- Create: `frontend/src/features/code-execution/clientToolHandler.ts`
- Create: `frontend/src/features/code-execution/__tests__/clientToolHandler.test.ts`

This module subscribes to `chat.client_tool.dispatch` events through the existing `eventBus` (`frontend/src/core/websocket/eventBus.ts`), routes valid `calculate_js` calls to `runSandbox`, and sends the result back via `sendMessage` from `connection.ts`. Unknown tools or missing code yield synthetic error results.

**Important API details for the implementer (verified against the real modules):**

- `eventBus.on(type, callback)` returns an unsubscribe function. The callback receives the **full `BaseEvent`** object (fields: `type`, `payload`, `sequence`, `scope`, `correlation_id`, `id`, `timestamp`), not just the payload. The payload is at `event.payload`.
- `sendMessage` is a named export from `@/core/websocket/connection` that wraps `ws.send(JSON.stringify(...))` when the socket is OPEN.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/code-execution/__tests__/clientToolHandler.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BaseEvent } from '@/core/types/events'

// Mock the connection module so we can assert on sendMessage.
const sendMessageMock = vi.fn()
vi.mock('@/core/websocket/connection', () => ({
  sendMessage: (msg: unknown) => sendMessageMock(msg),
}))

// Mock runSandbox so the handler test doesn't spin up a real Worker.
const runSandboxMock = vi.fn()
vi.mock('../sandboxHost', () => ({
  runSandbox: (...args: unknown[]) => runSandboxMock(...args),
}))

// Use the real eventBus — it is a singleton module with no side effects
// and we want to exercise the actual subscription path. This also removes
// the risk of drift between a hand-rolled mock and the production API.
import { eventBus } from '@/core/websocket/eventBus'
import { registerClientToolHandler } from '../clientToolHandler'

function makeEvent(payload: Record<string, unknown>): BaseEvent {
  return {
    id: 'evt-1',
    type: 'chat.client_tool.dispatch',
    sequence: '1-0',
    scope: 'user:u1',
    correlation_id: 'c1',
    timestamp: new Date().toISOString(),
    payload,
  }
}

describe('registerClientToolHandler', () => {
  let unregister: () => void

  beforeEach(() => {
    sendMessageMock.mockReset()
    runSandboxMock.mockReset()
    eventBus.clear()
    unregister = registerClientToolHandler()
  })

  afterEach(() => {
    unregister()
    eventBus.clear()
  })

  it('runs calculate_js and sends the result back', async () => {
    runSandboxMock.mockResolvedValue({ stdout: '4', error: null })

    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-1',
      tool_name: 'calculate_js',
      arguments: { code: 'console.log(2+2)' },
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    // yield to pending microtasks
    await new Promise((r) => setTimeout(r, 0))
    await new Promise((r) => setTimeout(r, 0))

    expect(runSandboxMock).toHaveBeenCalledWith('console.log(2+2)', 5000, 4096)
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-1',
      result: { stdout: '4', error: null },
    })
  })

  it('sends an error result when tool_name is unknown', async () => {
    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-2',
      tool_name: 'python_exec',
      arguments: { code: 'print(1)' },
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    await new Promise((r) => setTimeout(r, 0))

    expect(runSandboxMock).not.toHaveBeenCalled()
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-2',
      result: { stdout: '', error: 'Unknown client tool: python_exec' },
    })
  })

  it('sends an error result when code is missing', async () => {
    eventBus.emit(makeEvent({
      session_id: 's1',
      tool_call_id: 'tc-3',
      tool_name: 'calculate_js',
      arguments: {},
      timeout_ms: 5000,
      target_connection_id: 'conn-1',
    }))

    await new Promise((r) => setTimeout(r, 0))

    expect(runSandboxMock).not.toHaveBeenCalled()
    expect(sendMessageMock).toHaveBeenCalledWith({
      type: 'chat.client_tool.result',
      tool_call_id: 'tc-3',
      result: { stdout: '', error: 'No code provided' },
    })
  })
})
```

- [ ] **Step 2: Run the tests — expect failure**

Run: `pnpm --filter frontend vitest run src/features/code-execution/__tests__/clientToolHandler.test.ts`
Expected: failure — the module does not exist.

- [ ] **Step 3: Create the handler**

Create `frontend/src/features/code-execution/clientToolHandler.ts`:

```typescript
/* clientToolHandler.ts — bridges the WebSocket event bus to the
 * sandbox host. Registered once at app startup; the returned cleanup
 * function is the unsubscribe callback supplied by eventBus.on.
 */

import type { BaseEvent } from '@/core/types/events'
import { eventBus } from '@/core/websocket/eventBus'
import { sendMessage } from '@/core/websocket/connection'
import { runSandbox } from './sandboxHost'

const MAX_OUTPUT_BYTES = 4096

interface DispatchPayload {
  session_id: string
  tool_call_id: string
  tool_name: string
  arguments: { code?: string } & Record<string, unknown>
  timeout_ms: number
  target_connection_id: string
}

function sendResult(
  toolCallId: string,
  result: { stdout: string; error: string | null },
): void {
  sendMessage({
    type: 'chat.client_tool.result',
    tool_call_id: toolCallId,
    result,
  })
}

export function registerClientToolHandler(): () => void {
  return eventBus.on('chat.client_tool.dispatch', (event: BaseEvent) => {
    // eventBus callbacks are sync — we start the async work but do not
    // await it here. The handler sends the result via sendMessage when
    // the sandbox resolves.
    void handleDispatch(event.payload as unknown as DispatchPayload)
  })
}

async function handleDispatch(ev: DispatchPayload): Promise<void> {
  if (ev.tool_name !== 'calculate_js') {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Unknown client tool: ${ev.tool_name}`,
    })
    return
  }

  const code = typeof ev.arguments?.code === 'string' ? ev.arguments.code : ''
  if (!code) {
    sendResult(ev.tool_call_id, { stdout: '', error: 'No code provided' })
    return
  }

  try {
    const result = await runSandbox(code, ev.timeout_ms, MAX_OUTPUT_BYTES)
    sendResult(ev.tool_call_id, result)
  } catch (e) {
    sendResult(ev.tool_call_id, {
      stdout: '',
      error: `Sandbox host crashed: ${e instanceof Error ? e.message : String(e)}`,
    })
  }
}
```

- [ ] **Step 4: Run the tests — verify they pass**

Run: `pnpm --filter frontend vitest run src/features/code-execution/__tests__/clientToolHandler.test.ts`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/code-execution/clientToolHandler.ts \
        frontend/src/features/code-execution/__tests__/clientToolHandler.test.ts
git commit -m "Add clientToolHandler bridging chat.client_tool.dispatch to sandbox host"
```

---

## Task 17: Register `clientToolHandler` at app startup

**Files:**
- Modify: `frontend/src/App.tsx` (or the equivalent top-level setup component)

- [ ] **Step 1: Locate the existing startup effect**

Open `frontend/src/App.tsx`. Find the top-level `useEffect` that sets up WebSocket subscriptions on mount. If there is no dedicated one, add one.

- [ ] **Step 2: Register the handler on mount**

Add the import:

```typescript
import { registerClientToolHandler } from '@/features/code-execution/clientToolHandler'
```

Inside the startup `useEffect`:

```typescript
useEffect(() => {
  // ... existing setup
  const unregisterClientTool = registerClientToolHandler()
  return () => {
    // ... existing teardown
    unregisterClientTool()
  }
}, [])
```

Merge with the existing effect rather than creating a new one, so there is only one lifecycle block.

- [ ] **Step 3: Type-check**

Run: `pnpm --filter frontend tsc --noEmit`
Expected: no type errors.

- [ ] **Step 4: Frontend build check**

Run: `pnpm --filter frontend run build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "Register clientToolHandler at app startup"
```

---

## Task 18: End-to-end verification and final build checks

This task runs the full regression suite and documents manual E2E verification. No code changes; it is the final gate before the feature is considered done.

- [ ] **Step 1: Run the full backend test suite**

Run: `uv run pytest -q`
Expected: zero failures.

- [ ] **Step 2: Run the full frontend test suite**

Run: `pnpm --filter frontend vitest run`
Expected: zero failures.

- [ ] **Step 3: Frontend production build**

Run: `pnpm --filter frontend run build`
Expected: build succeeds, no errors or warnings that would fail CI.

- [ ] **Step 4: Backend syntax sweep over changed files**

Run:
```bash
uv run python -m py_compile \
  shared/topics.py shared/events/chat.py shared/dtos/tools.py \
  backend/ws/manager.py backend/ws/event_bus.py backend/ws/router.py \
  backend/modules/chat/_handlers_ws.py \
  backend/modules/chat/_orchestrator.py \
  backend/modules/chat/_inference.py \
  backend/modules/tools/__init__.py \
  backend/modules/tools/_registry.py \
  backend/modules/tools/_client_dispatcher.py
```
Expected: exit code 0.

- [ ] **Step 5: Manual E2E verification (document results in PR description)**

Start the stack (per project README) and run through each scenario. Record pass/fail and any observations.

1. **Erdbeer meme** — new session, weak model (GLM-4.5 Flash or DeepSeek), prompt: *"Wie viele 'r' sind im Wort Erdbeere?"*. Expect: model calls `calculate_js`, sees 3, answers 3.
2. **Exact arithmetic** — prompt: *"Rechne mir 2^53 + 1 genau aus."* Expect: model uses `BigInt`, answers `9007199254740993`.
3. **JSON parsing** — prompt with `{"a":1,"b":[2,3]}`: *"Zähle alle Zahlenwerte."* Expect: tool is used, correct count.
4. **Hard-stop failure** — prompt: *"Ruf `calculate_js` mit `code: fetch('http://example.com')` auf."* Expect: error result explains network restriction, model explains to user.
5. **Toggle off** — disable `code_execution` in the session, repeat (1). Expect: model does not call the tool.
6. **Multi-tab** — open two tabs on the same session, send a message in tab 1. Expect: only tab 1 shows the tool-call activity indicator, tab 2 stays silent, answer appears in tab 1.
7. **Disconnect during wait** — snippet that burns CPU (`for(let i=0;i<1e9;i++){}`), close the tab mid-execution. Expect: server logs show `"Client disconnected before tool completed"`, inference loop finishes with an error result, no hang.

- [ ] **Step 6: Final commit — if any test or formatting fixups were needed**

If Steps 1–4 exposed issues that required small fixes, commit them:

```bash
git add <the-files>
git commit -m "Fix <issue> uncovered in final verification sweep"
```

If nothing needed fixing, skip this step.

---

## Notes for the implementer

- **Module boundaries matter** (CLAUDE.md). Do not import `_client_dispatcher` from outside `backend/modules/tools/` — only `get_client_dispatcher()` is public.
- **Never publish without a fanout entry** (INS-011). Task 1 already adds `CHAT_CLIENT_TOOL_DISPATCH` to `_FANOUT`; double-check it landed.
- **Logs are Claude-oriented** (CLAUDE.md): every new log line should be structured enough that grep-and-filter works on correlation ids and tool call ids.
- **Stateless per call**: do not be tempted to cache the Web Worker between calls "for performance". A fresh Worker is the state guarantee.
- **No scope creep**: no matter how tempting, do **not** add a second client tool in this plan, do **not** generalise for Pyodide, do **not** touch unrelated tool groups.
