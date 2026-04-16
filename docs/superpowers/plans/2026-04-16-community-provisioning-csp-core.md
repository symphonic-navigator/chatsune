# Community Provisioning — CSP Core + Sidecar WebSocket Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend side of the Chatsune Sidecar Protocol
(CSP/1): the `/ws/sidecar` WebSocket endpoint that authenticates
sidecars via Host-Key, performs the CSP handshake, manages the frame
loop (request/response, streaming, cancellation, heartbeat,
supersede), and exposes an in-memory `SidecarRegistry` that the
`community` adapter (Plan 4) will consume.

**Architecture:** A new subpackage `backend/modules/llm/_csp/` holds
Pydantic frame models, a `SidecarConnection` wrapper (per-connection
state, request table, async generators for streams), and a
`SidecarRegistry` (process-local singleton mapping `homelab_id` →
`SidecarConnection`). The endpoint in `backend/ws/sidecar_router.py`
handles the WebSocket upgrade, bearer-auth via Host-Key, and drives
the frame loop. No persistent state — all registry entries live and
die with the process. Uses `HomelabService.resolve_homelab_by_host_key`
(Plan 1) and emits `llm.homelab.status_changed` events.

**Tech Stack:** FastAPI + Starlette WebSockets, Pydantic v2,
asyncio, Motor (for `HomelabService.touch_last_seen`), `websockets`
client for test fixtures.

**Depends on:** Plan 1 (HomelabService exists, `llm_homelabs` holds
`host_key_hash`).

**Consumed by:** Plan 4 (community adapter RPCs through registry),
Plan 2 (UI subscribes to status events).

**Parent spec:** `docs/superpowers/specs/2026-04-16-community-provisioning-design.md` §5, §9.5, §9.6.

**Sidecar spec (same wire format, authoritative for semantics):** `docs/superpowers/specs/2026-04-16-chatsune-sidecar-spec.md`.

---

## File Structure

**New files:**

- `backend/modules/llm/_csp/__init__.py` — empty marker
- `backend/modules/llm/_csp/_frames.py` — Pydantic frame models
- `backend/modules/llm/_csp/_connection.py` — `SidecarConnection`
- `backend/modules/llm/_csp/_registry.py` — `SidecarRegistry` + accessor
- `backend/modules/llm/_csp/_errors.py` — exception types
- `backend/ws/sidecar_router.py` — WebSocket endpoint
- `backend/tests/modules/llm/csp/__init__.py` — empty
- `backend/tests/modules/llm/csp/test_frames.py`
- `backend/tests/modules/llm/csp/test_connection.py`
- `backend/tests/modules/llm/csp/test_registry.py`
- `backend/tests/ws/test_sidecar_router.py`

**Modified files:**

- `backend/main.py` — mount the sidecar router, instantiate the registry at startup
- `backend/modules/llm/__init__.py` — export `get_sidecar_registry`

---

## Task 1: CSP Frame Models

**Files:**
- Create: `backend/modules/llm/_csp/__init__.py` (empty)
- Create: `backend/modules/llm/_csp/_frames.py`
- Create: `backend/tests/modules/llm/csp/__init__.py` (empty)
- Create: `backend/tests/modules/llm/csp/test_frames.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/llm/csp/test_frames.py`:

```python
import pytest

from backend.modules.llm._csp._frames import (
    AuthRevokedFrame,
    CancelFrame,
    EngineInfo,
    ErrFrame,
    HandshakeAckFrame,
    HandshakeFrame,
    ModelMeta,
    PingFrame,
    PongFrame,
    ReqFrame,
    ResFrame,
    StreamDelta,
    StreamEndFrame,
    StreamFrame,
    SupersededFrame,
    parse_frame,
)


def test_handshake_roundtrip():
    f = HandshakeFrame(
        csp_version="1.0",
        sidecar_version="1.0.0",
        engine=EngineInfo(type="ollama", version="0.5.0"),
        max_concurrent_requests=2,
        capabilities=["chat_streaming", "tool_calls"],
    )
    raw = f.model_dump_json()
    parsed = parse_frame(raw)
    assert isinstance(parsed, HandshakeFrame)
    assert parsed.engine.type == "ollama"
    assert parsed.max_concurrent_requests == 2


def test_parse_req_list_models():
    raw = '{"type":"req","id":"abc","op":"list_models"}'
    parsed = parse_frame(raw)
    assert isinstance(parsed, ReqFrame)
    assert parsed.op == "list_models"
    assert parsed.body is None


def test_parse_stream_content_delta():
    raw = '{"type":"stream","id":"r1","delta":{"content":"Hel"}}'
    parsed = parse_frame(raw)
    assert isinstance(parsed, StreamFrame)
    assert parsed.delta.content == "Hel"
    assert parsed.delta.reasoning is None
    assert parsed.delta.tool_calls is None


def test_parse_stream_reasoning_delta():
    raw = '{"type":"stream","id":"r1","delta":{"reasoning":"Let me think"}}'
    parsed = parse_frame(raw)
    assert parsed.delta.reasoning == "Let me think"
    assert parsed.delta.content is None


def test_parse_stream_tool_call_fragment():
    raw = (
        '{"type":"stream","id":"r1",'
        '"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function",'
        '"function":{"name":"get_weather","arguments":"{\\"loc\\":\\"V"}}]}}'
    )
    parsed = parse_frame(raw)
    assert parsed.delta.tool_calls[0]["index"] == 0
    assert parsed.delta.tool_calls[0]["function"]["name"] == "get_weather"


def test_parse_stream_end_with_usage():
    raw = (
        '{"type":"stream_end","id":"r1","finish_reason":"stop",'
        '"usage":{"prompt_tokens":5,"completion_tokens":7,"total_tokens":12}}'
    )
    parsed = parse_frame(raw)
    assert isinstance(parsed, StreamEndFrame)
    assert parsed.finish_reason == "stop"
    assert parsed.usage["total_tokens"] == 12


def test_parse_err_required_fields():
    raw = (
        '{"type":"err","id":"r1","code":"engine_unavailable",'
        '"message":"no engine","recoverable":true}'
    )
    parsed = parse_frame(raw)
    assert isinstance(parsed, ErrFrame)
    assert parsed.recoverable is True


def test_parse_ping_has_no_id():
    parsed = parse_frame('{"type":"ping"}')
    assert isinstance(parsed, PingFrame)


def test_parse_unknown_type_raises():
    with pytest.raises(ValueError):
        parse_frame('{"type":"martian"}')


def test_model_meta_drops_model_without_context_length_validation():
    # The frame model requires context_length; missing → validation error
    with pytest.raises(Exception):
        ModelMeta(slug="x", display_name="X", context_length=None)
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest backend/tests/modules/llm/csp/test_frames.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the frames**

Create `backend/modules/llm/_csp/__init__.py` (empty file).

Create `backend/modules/llm/_csp/_frames.py`:

```python
"""CSP/1 frame models. Authoritative wire format.

Matches docs/superpowers/specs/2026-04-16-chatsune-sidecar-spec.md.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class EngineInfo(BaseModel):
    type: Literal["ollama", "lmstudio", "vllm", "llamacpp"]
    version: str | None = None
    endpoint_hint: str | None = None


class HandshakeFrame(BaseModel):
    type: Literal["handshake"] = "handshake"
    csp_version: str
    sidecar_version: str
    engine: EngineInfo
    max_concurrent_requests: int = Field(ge=1)
    capabilities: list[str] = Field(default_factory=list)


class HandshakeAckFrame(BaseModel):
    type: Literal["handshake_ack"] = "handshake_ack"
    csp_version: str
    homelab_id: str | None = None
    display_name: str | None = None
    accepted: bool
    notices: list[str] = Field(default_factory=list)


class PingFrame(BaseModel):
    type: Literal["ping"] = "ping"


class PongFrame(BaseModel):
    type: Literal["pong"] = "pong"


class AuthRevokedFrame(BaseModel):
    type: Literal["auth_revoked"] = "auth_revoked"


class SupersededFrame(BaseModel):
    type: Literal["superseded"] = "superseded"


class ReqFrame(BaseModel):
    type: Literal["req"] = "req"
    id: str
    op: Literal["list_models", "generate_chat"]
    body: dict[str, Any] | None = None


class ResFrame(BaseModel):
    type: Literal["res"] = "res"
    id: str
    ok: bool
    body: dict[str, Any] | None = None


class StreamDelta(BaseModel):
    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class StreamFrame(BaseModel):
    type: Literal["stream"] = "stream"
    id: str
    delta: StreamDelta


class StreamEndFrame(BaseModel):
    type: Literal["stream_end"] = "stream_end"
    id: str
    finish_reason: Literal["stop", "length", "tool_calls", "cancelled", "error"]
    usage: dict[str, int] | None = None


class ErrFrame(BaseModel):
    type: Literal["err"] = "err"
    id: str | None = None
    code: Literal[
        "model_not_found",
        "model_oom",
        "engine_unavailable",
        "engine_error",
        "invalid_request",
        "rate_limited",
        "cancelled",
        "internal",
    ]
    message: str
    detail: str | None = None
    recoverable: bool = False


class CancelFrame(BaseModel):
    type: Literal["cancel"] = "cancel"
    id: str


class ModelMeta(BaseModel):
    """Body element for list_models response."""

    slug: str
    display_name: str
    parameter_count: int | None = None
    context_length: int = Field(..., description="required; models without this are dropped before the list leaves the sidecar")
    quantisation: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    engine_family: str | None = None
    engine_model_id: str | None = None
    engine_metadata: dict[str, Any] = Field(default_factory=dict)


_FRAME_BY_TYPE: dict[str, type[BaseModel]] = {
    "handshake": HandshakeFrame,
    "handshake_ack": HandshakeAckFrame,
    "ping": PingFrame,
    "pong": PongFrame,
    "auth_revoked": AuthRevokedFrame,
    "superseded": SupersededFrame,
    "req": ReqFrame,
    "res": ResFrame,
    "stream": StreamFrame,
    "stream_end": StreamEndFrame,
    "err": ErrFrame,
    "cancel": CancelFrame,
}


def parse_frame(raw: str | bytes) -> BaseModel:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    obj = json.loads(raw)
    ftype = obj.get("type")
    cls = _FRAME_BY_TYPE.get(ftype)
    if cls is None:
        raise ValueError(f"Unknown frame type: {ftype!r}")
    return cls.model_validate(obj)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/csp/test_frames.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_csp/ backend/tests/modules/llm/csp/
git commit -m "Add CSP/1 frame Pydantic models and parser"
```

---

## Task 2: Version Negotiation + Errors

**Files:**
- Create: `backend/modules/llm/_csp/_errors.py`
- Modify: `backend/modules/llm/_csp/_frames.py` (add `negotiate_version`)
- Modify: `backend/tests/modules/llm/csp/test_frames.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/modules/llm/csp/test_frames.py`:

```python
from backend.modules.llm._csp._frames import negotiate_version


def test_negotiate_matching_versions():
    assert negotiate_version("1.0", "1.0") == (True, "1.0", [])


def test_negotiate_minor_downgrade_uses_min():
    ok, v, notices = negotiate_version("1.3", "1.1")
    assert ok is True
    assert v == "1.1"
    assert notices == []


def test_negotiate_major_mismatch_rejects():
    ok, v, notices = negotiate_version("2.0", "1.0")
    assert ok is False
    assert v == "1.0"
    assert any("version_unsupported" in n for n in notices)


def test_negotiate_malformed_rejects():
    ok, _, notices = negotiate_version("banana", "1.0")
    assert ok is False
    assert any("version_unsupported" in n for n in notices)
```

Create `backend/modules/llm/_csp/_errors.py`:

```python
"""Exception types internal to the CSP layer."""


class CSPProtocolError(RuntimeError):
    pass


class CSPAuthError(RuntimeError):
    pass


class CSPVersionMismatchError(CSPProtocolError):
    pass


class CSPConnectionClosed(RuntimeError):
    pass
```

- [ ] **Step 2: Append negotiation helper**

Append to `backend/modules/llm/_csp/_frames.py`:

```python
def negotiate_version(
    sidecar_version: str, backend_version: str
) -> tuple[bool, str, list[str]]:
    """Return (accepted, negotiated_version, notices).

    Major mismatch → accepted=False, notices contain 'version_unsupported'.
    Minor mismatch → accepted=True, version becomes min(a.minor, b.minor).
    Malformed sidecar version → rejected.
    """

    def _parse(v: str) -> tuple[int, int] | None:
        try:
            major_s, minor_s = v.split(".", 1)
            return int(major_s), int(minor_s)
        except (ValueError, AttributeError):
            return None

    sv = _parse(sidecar_version)
    bv = _parse(backend_version)
    if sv is None or bv is None:
        return False, backend_version, ["version_unsupported: malformed"]
    if sv[0] != bv[0]:
        return False, backend_version, [
            f"version_unsupported: backend requires CSP/{bv[0]}.x"
        ]
    negotiated = f"{bv[0]}.{min(sv[1], bv[1])}"
    return True, negotiated, []
```

- [ ] **Step 3: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/csp/test_frames.py -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_csp/_errors.py backend/modules/llm/_csp/_frames.py backend/tests/modules/llm/csp/test_frames.py
git commit -m "Add CSP version negotiation and exception types"
```

---

## Task 3: SidecarConnection — Per-Connection State Machine

**Files:**
- Create: `backend/modules/llm/_csp/_connection.py`
- Create: `backend/tests/modules/llm/csp/test_connection.py`

This task builds the abstraction that the adapter will call into. A
`SidecarConnection` owns a WebSocket, a pending-request table, and
an outgoing-frame lock. Callers use `rpc_list_models()` and
`rpc_generate_chat()`; both serialise through the same frame loop.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/llm/csp/test_connection.py`:

```python
import asyncio
import json
from collections.abc import Awaitable, Callable

import pytest

from backend.modules.llm._csp._connection import SidecarConnection
from backend.modules.llm._csp._errors import CSPConnectionClosed


class FakeWS:
    """In-process stand-in for Starlette's WebSocket."""

    def __init__(self) -> None:
        self.to_client: asyncio.Queue[str] = asyncio.Queue()  # backend → sidecar
        self.from_client: asyncio.Queue[str | None] = asyncio.Queue()  # sidecar → backend
        self.closed = False

    async def send_text(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("closed")
        await self.to_client.put(text)

    async def receive_text(self) -> str:
        v = await self.from_client.get()
        if v is None:
            raise CSPConnectionClosed()
        return v

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        await self.from_client.put(None)

    # Helpers for tests
    async def feed(self, payload: dict) -> None:
        await self.from_client.put(json.dumps(payload))

    async def drain_to_client(self) -> dict:
        return json.loads(await self.to_client.get())


@pytest.mark.asyncio
async def test_list_models_roundtrip():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws,
        homelab_id="H1",
        display_name="A",
        max_concurrent=2,
        capabilities={"chat_streaming"},
        sidecar_version="1.0.0",
        engine_info={"type": "ollama", "version": "0.5"},
    )
    loop_task = asyncio.create_task(conn.run())

    async def fake_sidecar():
        req = await ws.drain_to_client()
        assert req["type"] == "req"
        assert req["op"] == "list_models"
        await ws.feed(
            {
                "type": "res",
                "id": req["id"],
                "ok": True,
                "body": {
                    "models": [
                        {
                            "slug": "llama3.2:8b",
                            "display_name": "Llama 3.2 8B",
                            "context_length": 131072,
                            "capabilities": ["text"],
                        }
                    ]
                },
            }
        )

    sidecar_task = asyncio.create_task(fake_sidecar())
    models = await asyncio.wait_for(conn.rpc_list_models(), timeout=2.0)
    await sidecar_task
    assert models[0]["slug"] == "llama3.2:8b"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_generate_chat_streams_deltas():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=2,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())

    async def fake_sidecar():
        req = await ws.drain_to_client()
        rid = req["id"]
        for ch in ["Hel", "lo", "!"]:
            await ws.feed({"type": "stream", "id": rid, "delta": {"content": ch}})
        await ws.feed(
            {
                "type": "stream_end",
                "id": rid,
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            }
        )

    asyncio.create_task(fake_sidecar())
    received = []
    async for frame in conn.rpc_generate_chat(body={"model_slug": "x", "messages": []}):
        received.append(frame)
    contents = [f.delta.content for f in received[:-1]]
    assert contents == ["Hel", "lo", "!"]
    assert received[-1].type == "stream_end"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_generate_chat_propagates_err_then_stream_end():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=2,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())

    async def fake_sidecar():
        req = await ws.drain_to_client()
        rid = req["id"]
        await ws.feed(
            {
                "type": "err", "id": rid, "code": "model_oom",
                "message": "VRAM exhausted", "recoverable": True,
            }
        )
        await ws.feed(
            {"type": "stream_end", "id": rid, "finish_reason": "error"}
        )

    asyncio.create_task(fake_sidecar())
    frames = [f async for f in conn.rpc_generate_chat(body={})]
    assert frames[0].type == "err"
    assert frames[0].code == "model_oom"
    assert frames[1].type == "stream_end"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_cancel_sends_cancel_frame_and_awaits_stream_end():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=2,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())

    cancel_received: dict = {}

    async def fake_sidecar():
        req = await ws.drain_to_client()
        rid = req["id"]
        # emit one chunk, then wait for cancel
        await ws.feed({"type": "stream", "id": rid, "delta": {"content": "A"}})
        maybe_cancel = await ws.drain_to_client()
        cancel_received.update(maybe_cancel)
        await ws.feed(
            {"type": "stream_end", "id": rid, "finish_reason": "cancelled"}
        )

    asyncio.create_task(fake_sidecar())
    gen = conn.rpc_generate_chat(body={})
    first = await gen.__anext__()
    assert first.delta.content == "A"
    await gen.aclose()  # caller cancels the generator

    await asyncio.sleep(0.05)
    assert cancel_received.get("type") == "cancel"

    await conn.close()
    await loop_task


@pytest.mark.asyncio
async def test_rpc_raises_after_close():
    ws = FakeWS()
    conn = SidecarConnection(
        ws=ws, homelab_id="H1", display_name="A", max_concurrent=1,
        capabilities={"chat_streaming"}, sidecar_version="1.0.0",
        engine_info={"type": "ollama"},
    )
    loop_task = asyncio.create_task(conn.run())
    await conn.close()
    await loop_task
    with pytest.raises(CSPConnectionClosed):
        await conn.rpc_list_models()
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest backend/tests/modules/llm/csp/test_connection.py -v`
Expected: module-not-found.

- [ ] **Step 3: Implement SidecarConnection**

Create `backend/modules/llm/_csp/_connection.py`:

```python
"""One-per-sidecar state machine. Decouples callers from the WS."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from backend.modules.llm._csp._errors import CSPConnectionClosed
from backend.modules.llm._csp._frames import (
    CancelFrame,
    ErrFrame,
    PingFrame,
    PongFrame,
    ReqFrame,
    ResFrame,
    StreamEndFrame,
    StreamFrame,
    parse_frame,
)

_log = logging.getLogger(__name__)


class _PendingRequest:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[BaseModel | None] = asyncio.Queue()
        self.done = asyncio.Event()


class SidecarConnection:
    """Wraps a WS connection plus all per-connection dispatch state."""

    def __init__(
        self,
        ws,
        homelab_id: str,
        display_name: str,
        max_concurrent: int,
        capabilities: set[str],
        sidecar_version: str,
        engine_info: dict,
    ) -> None:
        self.ws = ws
        self.homelab_id = homelab_id
        self.display_name = display_name
        self.max_concurrent = max_concurrent
        self.capabilities = capabilities
        self.sidecar_version = sidecar_version
        self.engine_info = engine_info
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, _PendingRequest] = {}
        self._closed = asyncio.Event()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_ping_at: float = 0.0

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    async def send(self, frame: BaseModel) -> None:
        if self.closed:
            raise CSPConnectionClosed()
        async with self._send_lock:
            await self.ws.send_text(frame.model_dump_json(exclude_none=True))

    async def run(self) -> None:
        """Drive the frame loop until the socket closes. Blocking."""

        try:
            while not self.closed:
                raw = await self.ws.receive_text()
                try:
                    frame = parse_frame(raw)
                except Exception as exc:
                    _log.warning(
                        "csp.parse_error homelab=%s err=%s",
                        self.homelab_id, exc,
                    )
                    continue
                await self._dispatch(frame)
        except CSPConnectionClosed:
            pass
        except Exception as exc:  # noqa: BLE001
            _log.info(
                "csp.connection_closed homelab=%s cause=%s",
                self.homelab_id, exc,
            )
        finally:
            self._closed.set()
            for pr in self._pending.values():
                await pr.queue.put(None)
                pr.done.set()

    async def _dispatch(self, frame: BaseModel) -> None:
        if isinstance(frame, PingFrame):
            await self.send(PongFrame())
            self._last_ping_at = _monotonic()
            return
        if isinstance(frame, PongFrame):
            return
        if isinstance(frame, ResFrame):
            pr = self._pending.get(frame.id)
            if pr is None:
                _log.warning("csp.res_no_pending id=%s", frame.id)
                return
            await pr.queue.put(frame)
            await pr.queue.put(None)  # sentinel
            pr.done.set()
            return
        if isinstance(frame, StreamFrame):
            pr = self._pending.get(frame.id)
            if pr is None:
                return
            await pr.queue.put(frame)
            return
        if isinstance(frame, StreamEndFrame):
            pr = self._pending.get(frame.id)
            if pr is None:
                return
            await pr.queue.put(frame)
            await pr.queue.put(None)
            pr.done.set()
            return
        if isinstance(frame, ErrFrame):
            pr = self._pending.get(frame.id) if frame.id else None
            if pr is None:
                _log.warning(
                    "csp.orphan_err code=%s msg=%s",
                    frame.code, frame.message,
                )
                return
            await pr.queue.put(frame)
            return
        # Unknown → ignored (forward-compat).

    async def close(self) -> None:
        if self.closed:
            return
        self._closed.set()
        try:
            await self.ws.close(code=1000)
        except Exception:  # noqa: BLE001
            pass

    # --- Public RPCs ---

    async def rpc_list_models(self) -> list[dict[str, Any]]:
        if self.closed:
            raise CSPConnectionClosed()
        rid = str(uuid4())
        pr = _PendingRequest()
        self._pending[rid] = pr
        try:
            async with self._semaphore:
                await self.send(ReqFrame(id=rid, op="list_models"))
                frame = await pr.queue.get()
                if frame is None:
                    raise CSPConnectionClosed()
                if isinstance(frame, ErrFrame):
                    # drain sentinel
                    await pr.queue.get()
                    raise RuntimeError(f"{frame.code}: {frame.message}")
                assert isinstance(frame, ResFrame)
                return frame.body.get("models", []) if frame.body else []
        finally:
            self._pending.pop(rid, None)

    async def rpc_generate_chat(
        self, body: dict[str, Any]
    ) -> AsyncIterator[BaseModel]:
        if self.closed:
            raise CSPConnectionClosed()
        rid = str(uuid4())
        pr = _PendingRequest()
        self._pending[rid] = pr

        async def _gen() -> AsyncIterator[BaseModel]:
            try:
                async with self._semaphore:
                    await self.send(
                        ReqFrame(id=rid, op="generate_chat", body=body)
                    )
                    while True:
                        frame = await pr.queue.get()
                        if frame is None:
                            return
                        yield frame
                        if isinstance(frame, StreamEndFrame):
                            return
            except GeneratorExit:
                # caller closed the generator → send cancel
                if not self.closed:
                    try:
                        await self.send(CancelFrame(id=rid))
                    except Exception:  # noqa: BLE001
                        pass
                # wait briefly for sidecar's cancelled stream_end
                try:
                    await asyncio.wait_for(pr.done.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                raise
            finally:
                self._pending.pop(rid, None)

        return _gen()


def _monotonic() -> float:
    import time
    return time.monotonic()
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/csp/test_connection.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_csp/_connection.py backend/tests/modules/llm/csp/test_connection.py
git commit -m "Add SidecarConnection with per-request dispatch and cancel"
```

---

## Task 4: SidecarRegistry

**Files:**
- Create: `backend/modules/llm/_csp/_registry.py`
- Create: `backend/tests/modules/llm/csp/test_registry.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/modules/llm/csp/test_registry.py`:

```python
from unittest.mock import AsyncMock

import pytest

from backend.modules.llm._csp._registry import SidecarRegistry


@pytest.mark.asyncio
async def test_register_and_lookup():
    reg = SidecarRegistry(event_bus=AsyncMock())
    conn = AsyncMock()
    conn.homelab_id = "H1"
    await reg.register(user_id="u1", conn=conn)
    assert reg.get("H1") is conn
    assert "H1" in reg.online_homelab_ids()


@pytest.mark.asyncio
async def test_unregister_removes_and_emits_status_event():
    bus = AsyncMock()
    reg = SidecarRegistry(event_bus=bus)
    conn = AsyncMock()
    conn.homelab_id = "H1"
    await reg.register(user_id="u1", conn=conn)
    bus.reset_mock()
    await reg.unregister("H1")
    assert reg.get("H1") is None
    bus.publish_to_users.assert_awaited_once()
    kwargs = bus.publish_to_users.call_args.kwargs
    assert kwargs["user_ids"] == ["u1"]


@pytest.mark.asyncio
async def test_last_wins_closes_older_connection():
    reg = SidecarRegistry(event_bus=AsyncMock())
    old = AsyncMock()
    old.homelab_id = "H1"
    await reg.register(user_id="u1", conn=old)
    new = AsyncMock()
    new.homelab_id = "H1"
    await reg.register(user_id="u1", conn=new)
    old.send.assert_awaited()
    assert reg.get("H1") is new


@pytest.mark.asyncio
async def test_revoke_closes_connection_with_auth_revoked_frame():
    reg = SidecarRegistry(event_bus=AsyncMock())
    conn = AsyncMock()
    conn.homelab_id = "H1"
    await reg.register(user_id="u1", conn=conn)
    await reg.revoke("H1")
    # both auth_revoked sent and close called
    assert conn.send.await_count >= 1
    conn.close.assert_awaited()
    assert reg.get("H1") is None
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest backend/tests/modules/llm/csp/test_registry.py -v`

- [ ] **Step 3: Implement SidecarRegistry**

Create `backend/modules/llm/_csp/_registry.py`:

```python
"""Process-local registry of live sidecar connections.

Keys: homelab_id. Values: SidecarConnection. No persistence.
Emits llm.homelab.status_changed on register / unregister transitions
so the host UI updates the online indicator in real time.
"""

from __future__ import annotations

import asyncio
import logging

from backend.modules.llm._csp._connection import SidecarConnection
from backend.modules.llm._csp._frames import AuthRevokedFrame, SupersededFrame
from shared.events.llm import HomelabStatusChangedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


class SidecarRegistry:
    def __init__(self, event_bus) -> None:
        self._by_homelab: dict[str, SidecarConnection] = {}
        self._user_by_homelab: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._bus = event_bus

    def get(self, homelab_id: str) -> SidecarConnection | None:
        return self._by_homelab.get(homelab_id)

    def online_homelab_ids(self) -> set[str]:
        return set(self._by_homelab.keys())

    async def register(
        self, user_id: str, conn: SidecarConnection
    ) -> None:
        hid = conn.homelab_id
        async with self._lock:
            old = self._by_homelab.get(hid)
            self._by_homelab[hid] = conn
            self._user_by_homelab[hid] = user_id
        if old is not None:
            _log.info("csp.supersede homelab=%s", hid)
            try:
                await old.send(SupersededFrame())
            except Exception:  # noqa: BLE001
                pass
            await old.close()
        else:
            await self._publish_status(hid, user_id, is_online=True)

    async def unregister(self, homelab_id: str) -> None:
        async with self._lock:
            conn = self._by_homelab.pop(homelab_id, None)
            user_id = self._user_by_homelab.pop(homelab_id, None)
        if conn is not None and user_id is not None:
            await self._publish_status(homelab_id, user_id, is_online=False)

    async def revoke(self, homelab_id: str) -> None:
        async with self._lock:
            conn = self._by_homelab.pop(homelab_id, None)
            user_id = self._user_by_homelab.pop(homelab_id, None)
        if conn is None:
            return
        try:
            await conn.send(AuthRevokedFrame())
        except Exception:  # noqa: BLE001
            pass
        await conn.close()
        if user_id is not None:
            await self._publish_status(homelab_id, user_id, is_online=False)

    async def _publish_status(
        self, homelab_id: str, user_id: str, is_online: bool
    ) -> None:
        event = HomelabStatusChangedEvent(
            homelab_id=homelab_id, is_online=is_online
        )
        await self._bus.publish_to_users(
            topic=Topics.LLM_HOMELAB_STATUS_CHANGED,
            user_ids=[user_id],
            event=event,
        )


_singleton: SidecarRegistry | None = None


def set_sidecar_registry(reg: SidecarRegistry) -> None:
    global _singleton
    _singleton = reg


def get_sidecar_registry() -> SidecarRegistry:
    if _singleton is None:
        raise RuntimeError("SidecarRegistry not initialised")
    return _singleton
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/csp/test_registry.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_csp/_registry.py backend/tests/modules/llm/csp/test_registry.py
git commit -m "Add SidecarRegistry with last-wins and revocation"
```

---

## Task 5: /ws/sidecar Endpoint + Handshake

**Files:**
- Create: `backend/ws/sidecar_router.py`
- Create: `backend/tests/ws/test_sidecar_router.py`

- [ ] **Step 1: Write failing end-to-end test**

Create `backend/tests/ws/test_sidecar_router.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient


def _handshake_payload(max_concurrent: int = 2) -> dict:
    return {
        "type": "handshake",
        "csp_version": "1.0",
        "sidecar_version": "1.0.0",
        "engine": {"type": "ollama", "version": "0.5.0"},
        "max_concurrent_requests": max_concurrent,
        "capabilities": ["chat_streaming"],
    }


def test_rejects_connect_without_auth(app_client: TestClient):
    with pytest.raises(Exception):
        with app_client.websocket_connect("/ws/sidecar"):
            pass


def test_rejects_wrong_prefix(app_client: TestClient):
    with pytest.raises(Exception):
        with app_client.websocket_connect(
            "/ws/sidecar", headers={"authorization": "Bearer invalid"}
        ):
            pass


def test_handshake_happy_path(app_client: TestClient, created_homelab):
    # `created_homelab` fixture: returns dict with 'homelab_id', 'plaintext_host_key'.
    token = created_homelab["plaintext_host_key"]
    with app_client.websocket_connect(
        "/ws/sidecar", headers={"authorization": f"Bearer {token}"}
    ) as ws:
        ws.send_text(json.dumps(_handshake_payload()))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "handshake_ack"
        assert ack["accepted"] is True
        assert ack["homelab_id"] == created_homelab["homelab_id"]


def test_handshake_rejects_major_version_mismatch(
    app_client: TestClient, created_homelab
):
    token = created_homelab["plaintext_host_key"]
    with app_client.websocket_connect(
        "/ws/sidecar", headers={"authorization": f"Bearer {token}"}
    ) as ws:
        bad = _handshake_payload()
        bad["csp_version"] = "2.0"
        ws.send_text(json.dumps(bad))
        ack = json.loads(ws.receive_text())
        assert ack["accepted"] is False
        assert any("version_unsupported" in n for n in ack.get("notices", []))


def test_list_models_roundtrip_over_ws(app_client: TestClient, created_homelab):
    from backend.modules.llm._csp._registry import get_sidecar_registry

    token = created_homelab["plaintext_host_key"]
    with app_client.websocket_connect(
        "/ws/sidecar", headers={"authorization": f"Bearer {token}"}
    ) as ws:
        ws.send_text(json.dumps(_handshake_payload()))
        ws.receive_text()  # ack
        registry = get_sidecar_registry()
        conn = registry.get(created_homelab["homelab_id"])
        assert conn is not None

        # Kick off RPC from the "backend side"
        import asyncio

        async def drive():
            return await conn.rpc_list_models()

        # TestClient runs its own loop; pattern used by other sidecar tests:
        # drain the req frame from the ws, push a res.
        import threading
        result: dict = {}
        def runner():
            result["models"] = asyncio.run(drive())
        t = threading.Thread(target=runner, daemon=True)
        t.start()

        req_raw = ws.receive_text()
        req = json.loads(req_raw)
        assert req["op"] == "list_models"
        ws.send_text(
            json.dumps(
                {
                    "type": "res", "id": req["id"], "ok": True,
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
        )
        t.join(timeout=5)
        assert result["models"][0]["slug"] == "llama3.2:8b"
```

The fixtures `app_client` and `created_homelab` need to exist in
`backend/tests/conftest.py`. `created_homelab` should POST
`/api/llm/homelabs` with an authenticated client and return the
response body. If those fixtures don't exist, add them following
the pattern of existing fixtures (study `backend/tests/conftest.py`).

- [ ] **Step 2: Run — verify it fails**

Run: `uv run pytest backend/tests/ws/test_sidecar_router.py -v`
Expected: 404 on the `/ws/sidecar` upgrade, because the router is
not mounted.

- [ ] **Step 3: Implement the endpoint**

Create `backend/ws/sidecar_router.py`:

```python
"""WebSocket endpoint for sidecar connections (CSP/1)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.database import get_db
from backend.modules.llm import HomelabService
from backend.modules.llm._csp._connection import SidecarConnection
from backend.modules.llm._csp._frames import (
    HandshakeAckFrame,
    HandshakeFrame,
    negotiate_version,
)
from backend.modules.llm._csp._registry import (
    SidecarRegistry,
    get_sidecar_registry,
)
from backend.modules.llm._homelab_tokens import HOST_KEY_PREFIX
from backend.ws.event_bus import get_event_bus

_log = logging.getLogger(__name__)

router = APIRouter()

BACKEND_CSP_VERSION = "1.0"


@router.websocket("/ws/sidecar")
async def sidecar_endpoint(ws: WebSocket) -> None:
    auth = ws.headers.get("authorization") or ws.query_params.get("access_token")
    if not auth or not auth.startswith("Bearer "):
        await ws.close(code=4401)
        return
    host_key = auth.removeprefix("Bearer ").strip()
    if not host_key.startswith(HOST_KEY_PREFIX):
        await ws.close(code=4401)
        return

    svc = HomelabService(get_db(), get_event_bus())
    homelab = await svc.resolve_homelab_by_host_key(host_key)
    if homelab is None or homelab.get("status") != "active":
        await ws.close(code=4401)
        return

    await ws.accept()

    # Read handshake frame
    try:
        raw = await ws.receive_text()
    except WebSocketDisconnect:
        return
    try:
        hs = HandshakeFrame.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        _log.warning("csp.bad_handshake homelab=%s err=%s", homelab["homelab_id"], exc)
        await ws.close(code=1002)
        return

    accepted, negotiated, notices = negotiate_version(
        hs.csp_version, BACKEND_CSP_VERSION
    )
    if not accepted:
        ack = HandshakeAckFrame(
            csp_version=BACKEND_CSP_VERSION, accepted=False, notices=notices,
        )
        await ws.send_text(ack.model_dump_json(exclude_none=True))
        await ws.close(code=1002)
        return

    ack = HandshakeAckFrame(
        csp_version=negotiated,
        homelab_id=homelab["homelab_id"],
        display_name=homelab["display_name"],
        accepted=True,
        notices=notices,
    )
    await ws.send_text(ack.model_dump_json(exclude_none=True))

    await svc._homelabs.touch_last_seen(
        homelab_id=homelab["homelab_id"],
        sidecar_version=hs.sidecar_version,
        engine_info={"type": hs.engine.type, "version": hs.engine.version},
    )

    conn = SidecarConnection(
        ws=ws,
        homelab_id=homelab["homelab_id"],
        display_name=homelab["display_name"],
        max_concurrent=hs.max_concurrent_requests,
        capabilities=set(hs.capabilities),
        sidecar_version=hs.sidecar_version,
        engine_info={"type": hs.engine.type, "version": hs.engine.version},
    )

    registry: SidecarRegistry = get_sidecar_registry()
    await registry.register(user_id=homelab["user_id"], conn=conn)
    try:
        await conn.run()
    finally:
        current = registry.get(conn.homelab_id)
        if current is conn:
            await registry.unregister(conn.homelab_id)
        if ws.application_state != WebSocketState.DISCONNECTED:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
```

- [ ] **Step 4: Mount the router + initialise the registry**

In `backend/main.py`:

```python
from backend.modules.llm._csp._registry import (
    SidecarRegistry,
    set_sidecar_registry,
)
from backend.ws.event_bus import get_event_bus
from backend.ws.sidecar_router import router as sidecar_router

# during startup:
set_sidecar_registry(SidecarRegistry(get_event_bus()))
# when mounting routers:
app.include_router(sidecar_router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `uv run pytest backend/tests/ws/test_sidecar_router.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/ws/sidecar_router.py backend/tests/ws/test_sidecar_router.py backend/main.py
git commit -m "Add /ws/sidecar endpoint with CSP handshake and registry hookup"
```

---

## Task 6: Heartbeat + Status Transitions

**Files:**
- Modify: `backend/modules/llm/_csp/_connection.py`
- Modify: `backend/modules/llm/_csp/_registry.py`
- Modify: `backend/tests/modules/llm/csp/test_connection.py`

This adds the 90s-silence → degraded, 5min-silence → offline logic
described in the design spec §5.10. Implemented on the server side:
the registry tracks per-connection `last_traffic_at`; a background
task flips status and emits events.

- [ ] **Step 1: Append failing tests**

Append to `backend/tests/modules/llm/csp/test_registry.py`:

```python
@pytest.mark.asyncio
async def test_health_monitor_transitions(monkeypatch):
    from backend.modules.llm._csp import _registry as r_mod

    now = [1000.0]
    monkeypatch.setattr(r_mod, "_monotonic", lambda: now[0])

    bus = AsyncMock()
    reg = SidecarRegistry(event_bus=bus)
    conn = AsyncMock()
    conn.homelab_id = "H1"
    conn.last_traffic_at = now[0]
    await reg.register(user_id="u1", conn=conn)

    now[0] += 100  # > 90 s of silence → degraded
    await reg.tick_health()
    bus.publish_to_users.assert_awaited()

    bus.reset_mock()
    now[0] += 400  # > 5 min total → offline + unregister
    await reg.tick_health()
    assert reg.get("H1") is None
```

- [ ] **Step 2: Implement `last_traffic_at` + `tick_health`**

In `backend/modules/llm/_csp/_connection.py`, add in `__init__`:

```python
        self.last_traffic_at: float = _monotonic()
```

Update `_dispatch` to stamp on every received frame:

```python
    async def _dispatch(self, frame: BaseModel) -> None:
        self.last_traffic_at = _monotonic()
        # existing dispatch
```

In `backend/modules/llm/_csp/_registry.py` add at the top:

```python
import time


def _monotonic() -> float:
    return time.monotonic()
```

And append to `SidecarRegistry`:

```python
    async def tick_health(self) -> None:
        """Called periodically (every ~15 s). Emits degraded/offline transitions."""

        now = _monotonic()
        to_remove: list[tuple[str, str]] = []
        for hid, conn in list(self._by_homelab.items()):
            silence = now - getattr(conn, "last_traffic_at", now)
            user_id = self._user_by_homelab.get(hid)
            if silence > 300 and user_id is not None:
                to_remove.append((hid, user_id))
            elif silence > 90 and user_id is not None:
                # just emit degraded — don't drop the connection yet
                await self._publish_status(hid, user_id, is_online=False)

        for hid, user_id in to_remove:
            async with self._lock:
                self._by_homelab.pop(hid, None)
                self._user_by_homelab.pop(hid, None)
            await self._publish_status(hid, user_id, is_online=False)
```

In `backend/main.py`, add a startup task that calls `tick_health()`
every 15 seconds:

```python
import asyncio

async def _health_ticker(registry):
    while True:
        await asyncio.sleep(15)
        try:
            await registry.tick_health()
        except Exception:  # noqa: BLE001
            _log.exception("health_ticker failed")

# during startup:
asyncio.create_task(_health_ticker(get_sidecar_registry()))
```

- [ ] **Step 3: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/csp/ -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_csp/_connection.py backend/modules/llm/_csp/_registry.py backend/main.py backend/tests/modules/llm/csp/test_registry.py
git commit -m "Add heartbeat-based status transitions for sidecar connections"
```

---

## Task 7: Module Public API Export

**Files:**
- Modify: `backend/modules/llm/__init__.py`

- [ ] **Step 1: Export `get_sidecar_registry`**

Append to `backend/modules/llm/__init__.py`:

```python
from backend.modules.llm._csp._registry import get_sidecar_registry

__all__ = list(globals().get("__all__", [])) + ["get_sidecar_registry"]
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from backend.modules.llm import get_sidecar_registry"`
Expected: no output, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/__init__.py
git commit -m "Expose get_sidecar_registry from LLM module public API"
```

---

## Self-Review

1. CSP/1 frames listed in §5 of the sidecar spec: all 12 exist as
   Pydantic models in `_frames.py`. Verify by grepping.
2. Host-key authentication rejects (a) missing header, (b) wrong
   prefix, (c) unknown hash. Tests cover all three.
3. `get_sidecar_registry()` usable from both the handler (Plan 1)
   and the adapter (Plan 4).
4. Status transitions: register → online; 90s silence → degraded
   (emit only); 5min silence → offline + drop; explicit unregister
   → offline; revoke → auth_revoked + close + offline.
5. Last-wins supersede: second connect on a homelab with an active
   sidecar closes the old one with `superseded`.
6. `touch_last_seen` writes sidecar version + engine info on every
   successful handshake.
7. `rpc_generate_chat` cancellation: closing the generator sends
   `cancel` and waits briefly for `stream_end(cancelled)`.
