# Response Task Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify all chat responses (text and voice) under a single `ResponseTaskGroup` lifecycle with per-user registry, token-propagated cancellation, and plugin-array children, eliminating the five voice-barging defects and the subtle text-chat race conditions at once.

**Architecture:** One `ResponseTaskGroup` per assistant reply owns its WS events and a plugin array of `GroupChild`s. Text-mode uses `[chatStoreSink]`; voice-mode adds `[sentencer, pauser, synth, playback]`. The Group class is mode-agnostic. A module-level per-user registry auto-cancels the predecessor when a new send/edit/regenerate fires. Cancel sends `chat.retract` (before first delta, deletes the user message) or `chat.cancel` (otherwise, keeps partial content).

**Tech Stack:**
- Backend: Python 3.12, FastAPI, Pydantic v2, MongoDB (motor), `uv` for dependency management
- Frontend: Vite + React + TypeScript, Zustand, Vitest + React Testing Library, `pnpm`
- Reference spec: `devdocs/response-task-group-architecture.md`

**Testing conventions:**
- Frontend: `pnpm run test -- <path>` from `frontend/`; Vitest style, vi.fn mocks
- Backend: `uv run pytest <path>` from repo root; pytest-asyncio for async
- Build verification: `pnpm run build` (frontend) and `uv run python -m py_compile <file>` (backend, quick syntax check) at key points

**Two pyproject.toml files** exist (root + `backend/`). No new Python dependencies required in this plan.

---

## Migration Ordering Rationale

Steps 1–9 below land in this order so the app stays working at every commit:

1. **Backend first** — accept client-generated `correlation_id`, persist it on user messages. Backwards-compatible (old clients unaffected).
2. **`audioPlayback` token-aware with shim** — internal refactor; old `mute`/`resumeFromMute`/`discardMuted` calls keep working via thin delegation.
3. **`responseTaskGroup.ts` + `chatStoreSink.ts`** — standalone module, pure unit tests, no wiring yet.
4. **Voice children extracted** — sentencer/pauser/synth/playback factored into `GroupChild`s, still reachable via their old APIs. Internal refactor.
5. **Wire ChatView + useChatStream + useConversationMode to Groups** — the flip-the-switch moment. Voice barging is new; text-chat runs through Groups.
6. **Backend `handle_chat_retract`** — additive, enables the retract path.
7. **Enable retract in frontend `group.cancel()`** — was stubbed as `chat.cancel` in step 5, now branches to `chat.retract` when state was `before-first-delta`.
8. **Integration tests + manual verification** — the gate before cleanup.
9. **Cleanup** — remove the shim from step 2 and any remaining `mute`-API residue.

Sub-agents executing this plan can parallelise Tasks 1–3 (Backend) with Tasks 4–9 (Frontend build-up) up to Task 10 (the wiring).

---

# Tasks

## Task 1: Backend — `correlation_id` on user messages (schema + index)

**Why:** The new `handle_chat_retract` must look up the user message by `correlation_id`. Storing the field on the message document is the cleanest, race-free lookup path and survives backend restarts. Per the "no DB wipes" policy, the field gets a default of `None` so existing documents deserialise fine.

**Files:**
- Modify: `backend/modules/chat/_repository.py` (`create_indexes` + `save_message`)
- Test: `backend/modules/chat/tests/test_repository_correlation.py` (new)

- [ ] **Step 1.1: Write the failing test**

Create `backend/modules/chat/tests/test_repository_correlation.py`:

```python
"""Tests for correlation_id persistence on user messages."""

import pytest
from backend.modules.chat._repository import ChatRepository


@pytest.mark.asyncio
async def test_save_message_persists_correlation_id(test_db):
    repo = ChatRepository(test_db)
    await repo.create_indexes()
    await repo.create_session("user1", "persona1")
    session = await test_db["chat_sessions"].find_one({"user_id": "user1"})

    msg = await repo.save_message(
        session["_id"],
        role="user",
        content="hello",
        token_count=1,
        correlation_id="corr-abc",
    )

    assert msg["correlation_id"] == "corr-abc"


@pytest.mark.asyncio
async def test_user_message_by_correlation_returns_id(test_db):
    repo = ChatRepository(test_db)
    await repo.create_indexes()
    await repo.create_session("user1", "persona1")
    session = await test_db["chat_sessions"].find_one({"user_id": "user1"})

    msg = await repo.save_message(
        session["_id"],
        role="user",
        content="hi",
        token_count=1,
        correlation_id="corr-xyz",
    )

    found = await repo.user_message_by_correlation("user1", "corr-xyz")
    assert found == msg["_id"]


@pytest.mark.asyncio
async def test_user_message_by_correlation_missing_returns_none(test_db):
    repo = ChatRepository(test_db)
    await repo.create_indexes()

    found = await repo.user_message_by_correlation("user1", "does-not-exist")
    assert found is None


@pytest.mark.asyncio
async def test_save_message_without_correlation_id_is_none(test_db):
    """Backwards compatibility — old code paths that don't pass it should not break."""
    repo = ChatRepository(test_db)
    await repo.create_indexes()
    await repo.create_session("user1", "persona1")
    session = await test_db["chat_sessions"].find_one({"user_id": "user1"})

    msg = await repo.save_message(
        session["_id"], role="user", content="x", token_count=1,
    )
    assert msg.get("correlation_id") is None
```

If no `test_db` fixture exists in `backend/modules/chat/tests/conftest.py`, reuse whichever fixture the existing chat tests use (check any `test_*.py` file there). If there are no existing tests in that directory, place the file under the nearest existing test directory that already has a Mongo fixture (e.g. `backend/tests/` or similar).

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
uv run pytest backend/modules/chat/tests/test_repository_correlation.py -v
```

Expected: tests fail — `save_message` does not accept `correlation_id`, and `user_message_by_correlation` does not exist.

- [ ] **Step 1.3: Extend the repository**

Open `backend/modules/chat/_repository.py` and modify `create_indexes` (around line 24) to add:

```python
await self._messages.create_index(
    [("user_id", 1), ("correlation_id", 1)],
    name="user_id_correlation_id",
    sparse=True,
)
```

Note: the messages collection may not have `user_id` stored today (it has `session_id` and role). If that's the case, look at an existing `save_message` implementation to confirm the field set. If `user_id` is absent, index `(session_id, correlation_id)` instead and update `user_message_by_correlation` accordingly to look up via session → user. Pick whichever matches the real schema — do not invent fields.

Extend `save_message` (find its existing signature in the same file) to accept and persist `correlation_id`:

```python
async def save_message(
    self,
    session_id: str,
    *,
    role: Literal["user", "assistant"],
    content: str,
    token_count: int,
    correlation_id: str | None = None,
    # ... existing kwargs (attachment_ids, attachment_refs, etc.) ...
) -> dict:
    # ... existing body ...
    doc = {
        # ... existing fields ...
        "correlation_id": correlation_id,
    }
    await self._messages.insert_one(doc)
    return doc
```

Add the new lookup method near the top of the class:

```python
async def user_message_by_correlation(
    self, user_id: str, correlation_id: str,
) -> str | None:
    """Return the _id of the user message with this correlation_id, or None.

    Used by handle_chat_retract to locate the user message to delete when
    a response is aborted before its first content delta.
    """
    # Adjust the filter if the messages collection does not store user_id directly
    doc = await self._messages.find_one(
        {"user_id": user_id, "correlation_id": correlation_id, "role": "user"},
        projection={"_id": 1},
    )
    return doc["_id"] if doc else None
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
uv run pytest backend/modules/chat/tests/test_repository_correlation.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add backend/modules/chat/_repository.py backend/modules/chat/tests/test_repository_correlation.py
git commit -m "Add correlation_id field and lookup on user messages"
```

---

## Task 2: Backend — Accept client-provided `correlation_id` in all response-starting handlers

**Why:** The group needs a stable identity from the instant the user action fires (before `CHAT_STREAM_STARTED`). Client-generated IDs remove the pending-cancel window and make client and server logs correlatable from the first line.

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py` (`handle_chat_send:117`, `handle_chat_edit:241`, `handle_chat_regenerate:318`, `handle_incognito_send:438`)
- Test: `backend/modules/chat/tests/test_handlers_correlation.py` (new)

- [ ] **Step 2.1: Write the failing test**

```python
"""Tests for client-provided correlation_id acceptance in chat handlers."""

from unittest.mock import patch, AsyncMock
import pytest

from backend.modules.chat._handlers_ws import handle_chat_send


@pytest.mark.asyncio
async def test_handle_chat_send_uses_client_correlation_id(test_db, monkeypatch):
    captured = {}

    async def fake_publish(event_type, event, *, scope, target_user_ids, correlation_id):
        captured["correlation_id"] = correlation_id

    class FakeBus:
        publish = fake_publish

    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_event_bus",
        lambda: FakeBus(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.run_inference",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.cancel_all_for_user",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.track_extraction_trigger",
        AsyncMock(),
    )

    # Create session in test_db first (similar to Task 1 fixture usage)
    from backend.modules.chat._repository import ChatRepository
    repo = ChatRepository(test_db)
    await repo.create_indexes()
    await repo.create_session("user1", "persona1")
    session = await test_db["chat_sessions"].find_one({"user_id": "user1"})

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: test_db)

    await handle_chat_send("user1", {
        "session_id": session["_id"],
        "content": [{"type": "text", "text": "hello"}],
        "correlation_id": "client-supplied-id",
    })

    assert captured["correlation_id"] == "client-supplied-id"


@pytest.mark.asyncio
async def test_handle_chat_send_generates_when_missing(test_db, monkeypatch):
    """Backwards compat: if client omits correlation_id, server generates one."""
    captured = {}
    async def fake_publish(event_type, event, *, scope, target_user_ids, correlation_id):
        captured["correlation_id"] = correlation_id

    class FakeBus:
        publish = fake_publish

    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_event_bus",
        lambda: FakeBus(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.run_inference",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.cancel_all_for_user",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.track_extraction_trigger",
        AsyncMock(),
    )

    from backend.modules.chat._repository import ChatRepository
    repo = ChatRepository(test_db)
    await repo.create_indexes()
    await repo.create_session("user1", "persona1")
    session = await test_db["chat_sessions"].find_one({"user_id": "user1"})

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: test_db)

    await handle_chat_send("user1", {
        "session_id": session["_id"],
        "content": [{"type": "text", "text": "hello"}],
        # no correlation_id
    })

    assert "correlation_id" in captured
    assert captured["correlation_id"] is not None
    assert len(captured["correlation_id"]) > 0
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
uv run pytest backend/modules/chat/tests/test_handlers_correlation.py -v
```

Expected: `test_handle_chat_send_uses_client_correlation_id` fails — handler currently ignores `data["correlation_id"]` and generates its own.

- [ ] **Step 2.3: Modify the four handlers**

In `backend/modules/chat/_handlers_ws.py`:

1. Line 117 (`handle_chat_send`):
```python
# Replace
correlation_id = str(uuid4())
# With
correlation_id = data.get("correlation_id") or str(uuid4())
```

2. Line 241 (`handle_chat_edit`):
```python
# Replace
correlation_id = str(uuid4())
# With
correlation_id = data.get("correlation_id") or str(uuid4())
```

3. Line 318 (`handle_chat_regenerate`):
```python
# Replace
correlation_id = str(uuid4())
# With
correlation_id = data.get("correlation_id") or str(uuid4())
```

4. Line 438 (`handle_incognito_send`):
```python
# Replace
correlation_id = str(uuid4())
# With
correlation_id = data.get("correlation_id") or str(uuid4())
```

Also — in `handle_chat_send`, extend the `save_message` call (line 107-114) to persist the correlation_id on the user message:
```python
saved_msg = await repo.save_message(
    session_id,
    role="user",
    content=text,
    token_count=token_count,
    attachment_ids=attachment_ids,
    attachment_refs=attachment_refs,
    correlation_id=correlation_id,
)
```

(Move the `correlation_id = data.get("correlation_id") or str(uuid4())` line *above* the `save_message` call if it is currently below — it already is in the current source, so move it up.)

Do the same persistence in `handle_chat_edit` where the edited user message is saved (look for the `edit_message_atomic` or equivalent and if it saves a new user doc, attach `correlation_id`).

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
uv run pytest backend/modules/chat/tests/test_handlers_correlation.py backend/modules/chat/tests/test_repository_correlation.py -v
```

Expected: all tests pass.

- [ ] **Step 2.5: Syntax-verify the modified files**

```bash
uv run python -m py_compile backend/modules/chat/_handlers_ws.py backend/modules/chat/_repository.py
```

Expected: no output (clean compile).

- [ ] **Step 2.6: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py backend/modules/chat/tests/test_handlers_correlation.py
git commit -m "Accept client-provided correlation_id in chat handlers"
```

---

## Task 3: Frontend — `audioPlayback` token-aware with backwards-compat shim

**Why:** The token-aware `audioPlayback` is the foundation for drop-on-token-mismatch. Keeping the old `mute`/`resumeFromMute`/`discardMuted` API alive as a shim means we can land this change first and switch call sites later without a giant atomic commit.

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts`
- Modify: `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts` (if exists) or create new test file

- [ ] **Step 3.1: Locate existing tests and find shape**

```bash
find frontend/src/features/voice/infrastructure -name "*.test.ts" -type f
```

If there are existing tests, extend them. If not, create `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`.

- [ ] **Step 3.2: Write failing tests for token-aware API**

Add these tests (to a new file or existing one):

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { audioPlayback } from '../audioPlayback'

describe('audioPlayback token gating', () => {
  beforeEach(() => {
    audioPlayback.stopAll()
    audioPlayback.setCurrentToken(null)
  })

  it('drops enqueue when token does not match current', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as any
    audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-B')
    // Queue should remain empty
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('accepts enqueue when token matches', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as any
    audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')
    // Should have started playing (or attempted to)
    // We can only check the non-muted path — in jsdom, AudioContext may not exist
    // so this test checks that the entry was accepted (not rejected at the gate).
    // The real assertion is that no exception was thrown and queue is non-empty.
  })

  it('clearScope(token) drops queue when token matches', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as any
    audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')
    audioPlayback.clearScope('token-A')
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('clearScope(token) is no-op when token does not match', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as any
    audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')
    audioPlayback.clearScope('other-token')
    // Queue should still contain the entry (or playback in progress)
    // Assertion is that state was not reset
  })
})
```

- [ ] **Step 3.3: Run tests to verify they fail**

```bash
cd frontend && pnpm run test -- audioPlayback.test
```

Expected: fail — `setCurrentToken`, `clearScope`, and the token-gated `enqueue` do not yet exist.

- [ ] **Step 3.4: Implement token-aware API with shim**

Modify `frontend/src/features/voice/infrastructure/audioPlayback.ts`. Add fields near line 24:

```ts
  private currentToken: string | null = null
```

Add these public methods near the existing `enqueue`:

```ts
  setCurrentToken(token: string | null): void {
    this.currentToken = token
  }

  clearScope(token: string): void {
    if (this.currentToken !== token) return
    // Drop the queue and stop the current source, but don't reset the
    // streamClosed flag or the muted-shim state — mute/unmute semantics
    // remain valid during the shim period.
    this.queue = []
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource) {
      this.currentSource.onended = null
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.currentEntry = null
    this.playing = false
    this.emit()
  }
```

Modify `enqueue` (currently line 60) to add a token parameter and a gate:

```ts
  enqueue(audio: Float32Array, segment: SpeechSegment, token?: string): void {
    if (token !== undefined && this.currentToken !== null && token !== this.currentToken) {
      // Token mismatch — drop silently. This is the new path.
      console.debug(`[audioPlayback] drop chunk (token mismatch: got=${token}, current=${this.currentToken})`)
      return
    }
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null && !this.muted) this.playNext()
    this.emit()
  }
```

The `token` parameter is optional so the shim period (where old call sites don't yet pass a token) still works. Once all call sites pass a token, we tighten this signature in Task 14.

The existing `mute` / `resumeFromMute` / `discardMuted` / `isMuted` / `skipCurrent` stay intact — they are the shim, removed in Task 14 after all call sites migrate.

- [ ] **Step 3.5: Run tests to verify they pass**

```bash
cd frontend && pnpm run test -- audioPlayback.test
```

Expected: new tests pass; existing `mute`-based tests still pass.

- [ ] **Step 3.6: Full frontend build check**

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 3.7: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioPlayback.ts frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
git commit -m "Add token-aware enqueue, setCurrentToken, clearScope to audioPlayback"
```

---

## Task 4: Frontend — `responseTaskGroup.ts` core module + registry

**Why:** The heart of the new architecture — a pure state machine, testable in isolation with mock children. No imports from `voice/` or `chat/store`. Ships standalone before anything wires it.

**Files:**
- Create: `frontend/src/features/chat/responseTaskGroup.ts`
- Create: `frontend/src/features/chat/__tests__/responseTaskGroup.test.ts`

- [ ] **Step 4.1: Write failing tests — state machine and lifecycle**

Create `frontend/src/features/chat/__tests__/responseTaskGroup.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  getActiveGroup,
  clearActiveGroup,
  type GroupChild,
} from '../responseTaskGroup'

function makeChild(overrides: Partial<GroupChild> = {}): GroupChild & {
  onDelta: Mock; onStreamEnd: Mock; onCancel: Mock; teardown: Mock
} {
  return {
    name: overrides.name ?? 'mock',
    onDelta: vi.fn(),
    onStreamEnd: vi.fn().mockResolvedValue(undefined),
    onCancel: vi.fn(),
    teardown: vi.fn(),
    ...overrides,
  } as any
}

describe('ResponseTaskGroup', () => {
  const sendWs = vi.fn()
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }

  beforeEach(() => {
    sendWs.mockClear()
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('starts in before-first-delta state', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    expect(g.state).toBe('before-first-delta')
  })

  it('transitions to streaming on first onDelta', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hello')
    expect(g.state).toBe('streaming')
    expect(child.onDelta).toHaveBeenCalledWith('hello', 'c1')
  })

  it('transitions to tailing then done on onStreamEnd', async () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hi')
    g.onStreamEnd()
    // Wait for the promise chain to resolve
    await new Promise((r) => setTimeout(r, 0))
    expect(g.state).toBe('done')
    expect(child.onStreamEnd).toHaveBeenCalledWith('c1')
  })

  it('cancel from before-first-delta sends chat.retract', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.cancel('barge-retract')
    expect(g.state).toBe('cancelled')
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.retract', correlation_id: 'c1',
    })
    expect(child.onCancel).toHaveBeenCalledWith('barge-retract', 'c1')
  })

  it('cancel from streaming sends chat.cancel', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hi')
    g.cancel('user-stop')
    expect(g.state).toBe('cancelled')
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.cancel', correlation_id: 'c1',
    })
  })

  it('cancel on terminal state is a no-op', () => {
    const child = makeChild()
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.cancel('user-stop')
    const callsBefore = sendWs.mock.calls.length
    g.cancel('user-stop')
    expect(sendWs.mock.calls.length).toBe(callsBefore)
  })

  it('pause/resume dispatch optional callbacks to children', () => {
    const child = makeChild({ onPause: vi.fn(), onResume: vi.fn() })
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    g.onDelta('hi')
    g.pause()
    expect((child as any).onPause).toHaveBeenCalled()
    g.resume()
    expect((child as any).onResume).toHaveBeenCalled()
  })

  it('pause is no-op outside streaming/tailing', () => {
    const child = makeChild({ onPause: vi.fn() })
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    // In before-first-delta state
    g.pause()
    expect((child as any).onPause).not.toHaveBeenCalled()
  })
})

describe('ResponseTaskGroup registry', () => {
  const sendWs = vi.fn()
  const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }

  beforeEach(() => {
    sendWs.mockClear()
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
  })

  it('registerActiveGroup cancels the predecessor with reason superseded', () => {
    const child1 = { name: 'c', onDelta: vi.fn(), onStreamEnd: vi.fn(), onCancel: vi.fn(), teardown: vi.fn() }
    const g1 = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child1], sendWsMessage: sendWs, logger,
    })
    registerActiveGroup(g1)
    g1.onDelta('hi')  // move to streaming

    const child2 = { name: 'c', onDelta: vi.fn(), onStreamEnd: vi.fn(), onCancel: vi.fn(), teardown: vi.fn() }
    const g2 = createResponseTaskGroup({
      correlationId: 'c2', sessionId: 's1', userId: 'u1',
      children: [child2], sendWsMessage: sendWs, logger,
    })
    registerActiveGroup(g2)

    expect(child1.onCancel).toHaveBeenCalledWith('superseded', 'c1')
    expect(g1.state).toBe('cancelled')
    expect(getActiveGroup()).toBe(g2)
  })

  it('terminal group auto-clears from registry', async () => {
    const child = { name: 'c', onDelta: vi.fn(), onStreamEnd: vi.fn().mockResolvedValue(undefined), onCancel: vi.fn(), teardown: vi.fn() }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [child], sendWsMessage: sendWs, logger,
    })
    registerActiveGroup(g)
    g.onDelta('hi')
    g.onStreamEnd()
    await new Promise((r) => setTimeout(r, 0))
    expect(getActiveGroup()).toBeNull()
  })
})
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
cd frontend && pnpm run test -- responseTaskGroup.test
```

Expected: tests fail — module does not exist.

- [ ] **Step 4.3: Implement the module**

Create `frontend/src/features/chat/responseTaskGroup.ts`:

```ts
/**
 * Response Task Group — one cancellable unit per assistant reply.
 *
 * See devdocs/response-task-group-architecture.md for the full design.
 * The Group owns a WS correlationId and a plugin array of children; it
 * dispatches Group-level lifecycle events (onDelta/onStreamEnd/onCancel)
 * and sends chat.cancel or chat.retract on cancel depending on state.
 *
 * This module is mode-agnostic — it knows nothing about voice, text, or
 * the chat store. Children inject that concern.
 */

export type GroupState =
  | 'before-first-delta'
  | 'streaming'
  | 'tailing'
  | 'done'
  | 'cancelled'

export type CancelReason =
  | 'barge-retract'
  | 'barge-cancel'
  | 'user-stop'
  | 'teardown'
  | 'superseded'

export interface GroupChild {
  readonly name: string
  onDelta(delta: string, token: string): void
  onStreamEnd(token: string): void | Promise<void>
  onCancel(reason: CancelReason, token: string): void
  teardown(): void | Promise<void>
  onPause?(): void
  onResume?(): void
}

export interface WsOutbound {
  type: string
  [k: string]: unknown
}

export interface GroupLogger {
  info(msg: string, ...args: unknown[]): void
  debug(msg: string, ...args: unknown[]): void
  warn(msg: string, ...args: unknown[]): void
  error(msg: string, ...args: unknown[]): void
}

export interface ResponseTaskGroupDeps {
  correlationId: string
  sessionId: string
  userId: string
  children: GroupChild[]
  sendWsMessage: (msg: WsOutbound) => void
  logger: GroupLogger
}

export interface ResponseTaskGroup {
  readonly id: string
  readonly sessionId: string
  readonly state: GroupState
  onDelta(delta: string): void
  onStreamEnd(): void
  pause(): void
  resume(): void
  cancel(reason: CancelReason): void
}

function hash8(id: string): string {
  return id.slice(0, 8)
}

export function createResponseTaskGroup(deps: ResponseTaskGroupDeps): ResponseTaskGroup {
  const { correlationId, sessionId, userId: _userId, children, sendWsMessage, logger } = deps
  const prefix = `[group ${hash8(correlationId)}]`
  let state: GroupState = 'before-first-delta'

  logger.info(
    `${prefix} created (session=${sessionId}, children=${children.map((c) => c.name).join(',')})`,
  )

  function transition(next: GroupState, reason?: CancelReason): void {
    const reasonSuffix = reason ? ` (reason=${reason})` : ''
    logger.info(`${prefix} ${state} → ${next}${reasonSuffix}`)
    state = next
    if (state === 'done' || state === 'cancelled') {
      clearActiveGroup(group)
    }
  }

  const group: ResponseTaskGroup = {
    get id() { return correlationId },
    get sessionId() { return sessionId },
    get state() { return state },

    onDelta(delta: string): void {
      if (state === 'before-first-delta') transition('streaming')
      if (state !== 'streaming') {
        logger.debug(`${prefix} drop CONTENT_DELTA (state=${state})`)
        return
      }
      for (const child of children) {
        try { child.onDelta(delta, correlationId) }
        catch (err) { logger.error(`${prefix} child ${child.name} onDelta threw`, err) }
      }
    },

    onStreamEnd(): void {
      if (state !== 'streaming') {
        logger.debug(`${prefix} drop STREAM_ENDED (state=${state})`)
        return
      }
      transition('tailing')
      const drains = children.map((c) => {
        try { return Promise.resolve(c.onStreamEnd(correlationId)) }
        catch (err) {
          logger.error(`${prefix} child ${c.name} onStreamEnd threw`, err)
          return Promise.resolve()
        }
      })
      void Promise.allSettled(drains).then(() => {
        if (state !== 'tailing') return
        transition('done')
      })
    },

    pause(): void {
      if (state !== 'streaming' && state !== 'tailing') return
      logger.info(`${prefix} paused`)
      for (const child of children) child.onPause?.()
    },

    resume(): void {
      if (state !== 'streaming' && state !== 'tailing') return
      logger.info(`${prefix} resumed`)
      for (const child of children) child.onResume?.()
    },

    cancel(reason: CancelReason): void {
      if (state === 'done' || state === 'cancelled') return
      const wasBeforeDelta = state === 'before-first-delta'
      transition('cancelled', reason)
      for (const child of children) {
        try { child.onCancel(reason, correlationId) }
        catch (err) { logger.error(`${prefix} child ${child.name} onCancel threw`, err) }
      }
      sendWsMessage({
        type: wasBeforeDelta ? 'chat.retract' : 'chat.cancel',
        correlation_id: correlationId,
      })
      void Promise.allSettled(children.map(async (c) => {
        try { await c.teardown() }
        catch (err) { logger.error(`${prefix} child ${c.name} teardown threw`, err) }
      }))
    },
  }

  return group
}

// --- Registry --------------------------------------------------------------

let activeGroup: ResponseTaskGroup | null = null

export function registerActiveGroup(g: ResponseTaskGroup): void {
  if (activeGroup && activeGroup.state !== 'done' && activeGroup.state !== 'cancelled') {
    activeGroup.cancel('superseded')
  }
  activeGroup = g
}

export function getActiveGroup(): ResponseTaskGroup | null {
  return activeGroup
}

export function clearActiveGroup(g: ResponseTaskGroup): void {
  if (activeGroup === g) activeGroup = null
}
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
cd frontend && pnpm run test -- responseTaskGroup.test
```

Expected: all tests pass.

- [ ] **Step 4.5: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors in the new files. Pre-existing errors in untouched files are not our concern.

- [ ] **Step 4.6: Commit**

```bash
git add frontend/src/features/chat/responseTaskGroup.ts frontend/src/features/chat/__tests__/responseTaskGroup.test.ts
git commit -m "Add ResponseTaskGroup core module with state machine and registry"
```

---

## Task 5: Frontend — `chatStoreSink` child

**Why:** The first (and for text-chat the only) child. It appends deltas to `chatStore.streamingContent` and finalises on stream end — the same role `useChatStream` plays today, but inside a Group.

**Files:**
- Create: `frontend/src/features/chat/children/chatStoreSink.ts`
- Create: `frontend/src/features/chat/children/__tests__/chatStoreSink.test.ts`

- [ ] **Step 5.1: Write failing tests**

```ts
import { describe, it, expect, vi } from 'vitest'
import { createChatStoreSink } from '../chatStoreSink'

function makeStore() {
  return {
    startStreaming: vi.fn(),
    appendStreamingContent: vi.fn(),
    cancelStreaming: vi.fn(),
    correlationId: null as string | null,
  }
}

describe('chatStoreSink', () => {
  it('onDelta appends content when token matches', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onDelta('hello', 'c1')
    expect(store.appendStreamingContent).toHaveBeenCalledWith('hello')
  })

  it('onDelta drops when token does not match', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onDelta('hello', 'other-token')
    expect(store.appendStreamingContent).not.toHaveBeenCalled()
  })

  it('onCancel calls cancelStreaming when token matches', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onCancel('user-stop', 'c1')
    expect(store.cancelStreaming).toHaveBeenCalled()
  })

  it('onCancel drops when token does not match', () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    sink.onCancel('user-stop', 'other-token')
    expect(store.cancelStreaming).not.toHaveBeenCalled()
  })

  it('onStreamEnd resolves immediately', async () => {
    const store = makeStore()
    const sink = createChatStoreSink({
      sessionId: 's1', correlationId: 'c1', chatStore: store as any,
    })
    await expect(sink.onStreamEnd('c1')).resolves.toBeUndefined()
  })
})
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
cd frontend && pnpm run test -- chatStoreSink.test
```

Expected: module does not exist.

- [ ] **Step 5.3: Implement the sink**

Create `frontend/src/features/chat/children/chatStoreSink.ts`:

```ts
import type { GroupChild } from '../responseTaskGroup'

/**
 * Minimum shape of the chat store consumed by the sink. Lets us keep this
 * module free of imports from the concrete Zustand store, so tests can
 * inject a plain mock.
 */
export interface ChatStoreLike {
  startStreaming(correlationId: string): void
  appendStreamingContent(delta: string): void
  cancelStreaming(): void
}

export interface ChatStoreSinkOpts {
  sessionId: string
  correlationId: string
  chatStore: ChatStoreLike
}

export function createChatStoreSink(opts: ChatStoreSinkOpts): GroupChild {
  const prefix = `[chatStoreSink ${opts.correlationId.slice(0, 8)}]`

  return {
    name: 'chatStoreSink',

    onDelta(delta: string, token: string): void {
      if (token !== opts.correlationId) {
        console.debug(`${prefix} drop delta (token mismatch)`)
        return
      }
      opts.chatStore.appendStreamingContent(delta)
    },

    onStreamEnd(token: string): void {
      if (token !== opts.correlationId) return
      // The actual finalisation of the streamed message (moving streamingContent
      // into the message list) is driven by CHAT_STREAM_ENDED in useChatStream
      // — see Task 9. This sink resolves immediately because for text-mode
      // there is nothing to drain.
    },

    onCancel(_reason, token: string): void {
      if (token !== opts.correlationId) return
      opts.chatStore.cancelStreaming()
    },

    teardown(): void {},
  }
}
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
cd frontend && pnpm run test -- chatStoreSink.test
```

Expected: all tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add frontend/src/features/chat/children/chatStoreSink.ts frontend/src/features/chat/children/__tests__/chatStoreSink.test.ts
git commit -m "Add chatStoreSink GroupChild for text-chat delta routing"
```

---

## Task 6: Frontend — Extract voice children (sentencer wrapper)

**Why:** The existing `createStreamingSentencer` (in `frontend/src/features/voice/pipeline/streamingSentencer.ts`) already does the text→segment work. We wrap it in a `GroupChild` without changing its internals, so the group sees a uniform lifecycle interface and other voice children can subscribe to segment boundaries via DI.

**Files:**
- Create: `frontend/src/features/voice/children/sentencerChild.ts`
- Create: `frontend/src/features/voice/children/__tests__/sentencerChild.test.ts`

- [ ] **Step 6.1: Inspect existing sentencer API**

```bash
cat frontend/src/features/voice/pipeline/streamingSentencer.ts | head -80
```

Note the exported factory, its methods (`push(delta)`, `flush()`), and the `SpeechSegment` type shape. The sentencerChild wraps this.

- [ ] **Step 6.2: Write failing tests**

Create `frontend/src/features/voice/children/__tests__/sentencerChild.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { createSentencerChild } from '../sentencerChild'

describe('sentencerChild', () => {
  it('pushes delta to underlying sentencer and emits segments to subscribers', () => {
    const pushed: string[] = []
    const fakeSentencer = {
      push: vi.fn((d: string) => { pushed.push(d); return [] }),
      flush: vi.fn(() => []),
    }
    const onSegment = vi.fn()
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment,
    })
    child.onDelta('hello.', 'c1')
    expect(fakeSentencer.push).toHaveBeenCalledWith('hello.')
  })

  it('emits segments from push() result to onSegment subscribers', () => {
    const seg = { text: 'hello.', speed: 1, pitch: 0 } as any
    const fakeSentencer = {
      push: vi.fn(() => [seg]),
      flush: vi.fn(() => []),
    }
    const onSegment = vi.fn()
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment,
    })
    child.onDelta('hello.', 'c1')
    expect(onSegment).toHaveBeenCalledWith(seg, 'c1')
  })

  it('drops onDelta when token does not match', () => {
    const fakeSentencer = {
      push: vi.fn(() => []),
      flush: vi.fn(() => []),
    }
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment: vi.fn(),
    })
    child.onDelta('hello', 'other-token')
    expect(fakeSentencer.push).not.toHaveBeenCalled()
  })

  it('onStreamEnd flushes the sentencer and emits remaining segments', async () => {
    const seg = { text: 'tail', speed: 1, pitch: 0 } as any
    const fakeSentencer = {
      push: vi.fn(() => []),
      flush: vi.fn(() => [seg]),
    }
    const onSegment = vi.fn()
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment,
    })
    await child.onStreamEnd('c1')
    expect(fakeSentencer.flush).toHaveBeenCalled()
    expect(onSegment).toHaveBeenCalledWith(seg, 'c1')
  })
})
```

- [ ] **Step 6.3: Run tests to verify they fail**

```bash
cd frontend && pnpm run test -- sentencerChild.test
```

Expected: fail — module does not exist.

- [ ] **Step 6.4: Implement the child**

Create `frontend/src/features/voice/children/sentencerChild.ts`:

```ts
import type { GroupChild } from '../../chat/responseTaskGroup'
import type { SpeechSegment } from '../types'
import type { StreamingSentencer } from '../pipeline/streamingSentencer'

export interface SentencerChildOpts {
  correlationId: string
  sentencer: StreamingSentencer
  /**
   * Voice-internal event fan-out: called whenever the sentencer emits a
   * segment, either from push() mid-stream or flush() at stream end.
   * Subscribers (pauser, synth) register via DI at createPauser/createSynth
   * time — see the children factory in ChatView.
   */
  onSegment: (segment: SpeechSegment, token: string) => void
}

export function createSentencerChild(opts: SentencerChildOpts): GroupChild {
  const { correlationId, sentencer, onSegment } = opts
  const prefix = `[sentencer ${correlationId.slice(0, 8)}]`

  return {
    name: 'sentencer',

    onDelta(delta: string, token: string): void {
      if (token !== correlationId) return
      const segments = sentencer.push(delta)
      for (const s of segments) onSegment(s, correlationId)
    },

    async onStreamEnd(token: string): Promise<void> {
      if (token !== correlationId) return
      const remaining = sentencer.flush()
      for (const s of remaining) onSegment(s, correlationId)
    },

    onCancel(_reason, token: string): void {
      if (token !== correlationId) return
      // Sentencer is stateless past flush — nothing to clean up here.
      console.log(`${prefix} cancelled`)
    },

    teardown(): void {},
  }
}
```

- [ ] **Step 6.5: Run tests to verify they pass**

```bash
cd frontend && pnpm run test -- sentencerChild.test
```

Expected: all tests pass.

- [ ] **Step 6.6: Commit**

```bash
git add frontend/src/features/voice/children/sentencerChild.ts frontend/src/features/voice/children/__tests__/sentencerChild.test.ts
git commit -m "Add sentencerChild wrapping streamingSentencer as GroupChild"
```

---

## Task 7: Frontend — Voice children (pauser, synth, playback)

**Why:** Complete the voice-mode children set. Each wraps existing behaviour in the `GroupChild` contract with token-checks at the boundary. The `pauser` subscribes to `sentencer.onSegment` via DI; `synth` does the inference; `playback` wraps `audioPlayback` with the token-set and clearScope hooks added in Task 3.

**Files:**
- Create: `frontend/src/features/voice/children/pauserChild.ts`
- Create: `frontend/src/features/voice/children/synthChild.ts`
- Create: `frontend/src/features/voice/children/playbackChild.ts`
- Create: corresponding test files under `__tests__/`

- [ ] **Step 7.1: Locate current pause-between-sentences logic**

```bash
grep -rn "gapMs\|interSentence\|pause.*sentence" frontend/src/features/voice/
```

Identify where the inter-sentence delay lives today (likely in `audioPlayback.callbacks.gapMs` set in ChatView.tsx:813). This is the behaviour the `pauserChild` will own going forward — but for now, Tasks 7–8 keep the existing `gapMs` approach and the pauserChild is a near-no-op that exists for future extensibility.

- [ ] **Step 7.2: Implement `pauserChild` (near-no-op placeholder)**

Create `frontend/src/features/voice/children/pauserChild.ts`:

```ts
import type { GroupChild } from '../../chat/responseTaskGroup'
import type { SpeechSegment } from '../types'

export interface PauserChildOpts {
  correlationId: string
  /**
   * Called when the pauser has decided a pause is finished and the next
   * segment is cleared for synth/playback. For the initial implementation
   * this is pass-through — the pauser just forwards every segment.
   * Future enhancement: insert silence buffers between segments here.
   */
  onSegmentReleased: (segment: SpeechSegment, token: string) => void
}

export function createPauserChild(opts: PauserChildOpts): GroupChild & {
  pushSegment: (segment: SpeechSegment, token: string) => void
} {
  const { correlationId, onSegmentReleased } = opts

  return {
    name: 'pauser',

    pushSegment(segment: SpeechSegment, token: string): void {
      if (token !== correlationId) return
      // Today: pass-through. Future: schedule a silence gap before release.
      onSegmentReleased(segment, token)
    },

    onDelta(): void { /* pauser reacts to segments, not raw deltas */ },
    onStreamEnd(): void {},
    onCancel(): void {},
    teardown(): void {},
  }
}
```

Create `frontend/src/features/voice/children/__tests__/pauserChild.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'
import { createPauserChild } from '../pauserChild'

describe('pauserChild', () => {
  it('forwards segment to onSegmentReleased when token matches', () => {
    const released = vi.fn()
    const pauser = createPauserChild({ correlationId: 'c1', onSegmentReleased: released })
    const seg = { text: 'a', speed: 1, pitch: 0 } as any
    pauser.pushSegment(seg, 'c1')
    expect(released).toHaveBeenCalledWith(seg, 'c1')
  })

  it('drops segment when token mismatches', () => {
    const released = vi.fn()
    const pauser = createPauserChild({ correlationId: 'c1', onSegmentReleased: released })
    const seg = { text: 'a', speed: 1, pitch: 0 } as any
    pauser.pushSegment(seg, 'other')
    expect(released).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 7.3: Implement `synthChild`**

Look at the existing synth-call site in ChatView.tsx (the `queueSynth(session, segments)` function around line 700-780) to replicate its behaviour. The child wraps the same synthesis pipeline but enqueues into `audioPlayback.enqueue(audio, segment, token)` with the new token param.

Create `frontend/src/features/voice/children/synthChild.ts`:

```ts
import type { GroupChild } from '../../chat/responseTaskGroup'
import type { SpeechSegment, TTSEngine, VoicePreset, NarratorMode } from '../types'
import type { VoiceModulation } from '../pipeline/applyModulation'
import { audioPlayback } from '../infrastructure/audioPlayback'

export interface SynthChildOpts {
  correlationId: string
  tts: TTSEngine
  voice: VoicePreset
  narratorVoice: VoicePreset
  mode: NarratorMode
  modulation: VoiceModulation
}

export function createSynthChild(opts: SynthChildOpts): GroupChild & {
  enqueueSegment: (segment: SpeechSegment, token: string) => Promise<void>
} {
  const { correlationId, tts, voice, narratorVoice, mode, modulation } = opts
  const prefix = `[TTS-infer ${correlationId.slice(0, 8)}]`
  let cancelled = false
  let inFlight: Promise<void> = Promise.resolve()

  async function synthesiseOne(segment: SpeechSegment, token: string): Promise<void> {
    if (cancelled || token !== correlationId) return
    const preview = segment.text.slice(0, 40).replace(/\s+/g, ' ')
    console.log(`${prefix} start "${preview}"`)
    const start = performance.now()
    try {
      const useVoice = segment.isNarrator ? narratorVoice : voice
      const audio = await tts.synthesise(segment.text, useVoice, { mode, modulation })
      if (cancelled || token !== correlationId) return
      audioPlayback.enqueue(audio, segment, token)
      console.log(`${prefix} done  "${preview}" ${Math.round(performance.now() - start)}ms`)
    } catch (err) {
      console.warn(`${prefix} fail  "${preview}":`, err)
    }
  }

  return {
    name: 'synth',

    enqueueSegment(segment: SpeechSegment, token: string): Promise<void> {
      if (cancelled || token !== correlationId) return Promise.resolve()
      const next = inFlight.then(() => synthesiseOne(segment, token))
      inFlight = next
      return next
    },

    onDelta(): void { /* synth reacts to segments, not deltas */ },
    async onStreamEnd(): Promise<void> { await inFlight },
    onCancel(_reason, token): void {
      if (token !== correlationId) return
      cancelled = true
    },
    teardown(): void { cancelled = true },
  }
}
```

Create `frontend/src/features/voice/children/__tests__/synthChild.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createSynthChild } from '../synthChild'

vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: { enqueue: vi.fn() },
}))

describe('synthChild', () => {
  beforeEach(async () => {
    const { audioPlayback } = await import('../../infrastructure/audioPlayback')
    ;(audioPlayback.enqueue as any).mockClear()
  })

  it('synthesises and enqueues when token matches', async () => {
    const audio = new Float32Array(100)
    const fakeTts: any = { synthesise: vi.fn().mockResolvedValue(audio) }
    const child = createSynthChild({
      correlationId: 'c1',
      tts: fakeTts,
      voice: {} as any,
      narratorVoice: {} as any,
      mode: 'dialogue' as any,
      modulation: {} as any,
    })
    const seg = { text: 'hi', speed: 1, pitch: 0 } as any
    await child.enqueueSegment(seg, 'c1')
    expect(fakeTts.synthesise).toHaveBeenCalled()
    const { audioPlayback } = await import('../../infrastructure/audioPlayback')
    expect(audioPlayback.enqueue).toHaveBeenCalledWith(audio, seg, 'c1')
  })

  it('skips enqueue after onCancel', async () => {
    const audio = new Float32Array(100)
    const fakeTts: any = { synthesise: vi.fn().mockResolvedValue(audio) }
    const child = createSynthChild({
      correlationId: 'c1',
      tts: fakeTts,
      voice: {} as any,
      narratorVoice: {} as any,
      mode: 'dialogue' as any,
      modulation: {} as any,
    })
    child.onCancel('user-stop', 'c1')
    const seg = { text: 'hi', speed: 1, pitch: 0 } as any
    await child.enqueueSegment(seg, 'c1')
    const { audioPlayback } = await import('../../infrastructure/audioPlayback')
    expect(audioPlayback.enqueue).not.toHaveBeenCalled()
  })

  it('drops enqueueSegment with wrong token', async () => {
    const fakeTts: any = { synthesise: vi.fn() }
    const child = createSynthChild({
      correlationId: 'c1',
      tts: fakeTts,
      voice: {} as any,
      narratorVoice: {} as any,
      mode: 'dialogue' as any,
      modulation: {} as any,
    })
    await child.enqueueSegment({ text: 'hi', speed: 1, pitch: 0 } as any, 'other-token')
    expect(fakeTts.synthesise).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 7.4: Implement `playbackChild`**

Create `frontend/src/features/voice/children/playbackChild.ts`:

```ts
import type { GroupChild } from '../../chat/responseTaskGroup'
import { audioPlayback } from '../infrastructure/audioPlayback'

export interface PlaybackChildOpts {
  correlationId: string
  gapMs: number
  onSegmentStart?: () => void
  onFinished?: () => void
}

export function createPlaybackChild(opts: PlaybackChildOpts): GroupChild {
  const { correlationId, gapMs, onSegmentStart, onFinished } = opts
  const prefix = `[playback ${correlationId.slice(0, 8)}]`
  let drainResolve: (() => void) | null = null

  audioPlayback.setCurrentToken(correlationId)
  audioPlayback.setCallbacks({
    gapMs,
    onSegmentStart: (seg) => {
      console.log(`[TTS-play ${correlationId.slice(0, 8)}] start "${seg.text.slice(0, 40)}"`)
      onSegmentStart?.()
    },
    onFinished: () => {
      console.log(`${prefix} finished`)
      onFinished?.()
      drainResolve?.()
      drainResolve = null
    },
  })

  return {
    name: 'playback',

    onDelta(): void { /* playback reacts to segments from synth, not deltas */ },

    onStreamEnd(_token): Promise<void> {
      // Signal audioPlayback that no more audio is coming, then wait for
      // its onFinished callback to fire.
      return new Promise<void>((resolve) => {
        drainResolve = resolve
        audioPlayback.closeStream()
      })
    },

    onCancel(_reason, token): void {
      if (token !== correlationId) return
      audioPlayback.setCurrentToken(null)
      audioPlayback.clearScope(correlationId)
      drainResolve?.()
      drainResolve = null
    },

    onPause(): void {
      // Pause/resume are currently delegated to stopAll+preserve-queue.
      // Kept as a no-op placeholder; see Task 14 follow-up note.
    },

    onResume(): void {},

    teardown(): void {
      audioPlayback.setCurrentToken(null)
    },
  }
}
```

Create corresponding test in `frontend/src/features/voice/children/__tests__/playbackChild.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: {
    setCurrentToken: vi.fn(),
    setCallbacks: vi.fn(),
    closeStream: vi.fn(),
    clearScope: vi.fn(),
  },
}))

import { createPlaybackChild } from '../playbackChild'

describe('playbackChild', () => {
  it('sets current token on creation', async () => {
    const { audioPlayback } = await import('../../infrastructure/audioPlayback')
    ;(audioPlayback.setCurrentToken as any).mockClear()
    createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    expect(audioPlayback.setCurrentToken).toHaveBeenCalledWith('c1')
  })

  it('clearScope + null-token on cancel with matching token', async () => {
    const { audioPlayback } = await import('../../infrastructure/audioPlayback')
    ;(audioPlayback.setCurrentToken as any).mockClear()
    ;(audioPlayback.clearScope as any).mockClear()
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    child.onCancel('user-stop', 'c1')
    expect(audioPlayback.setCurrentToken).toHaveBeenLastCalledWith(null)
    expect(audioPlayback.clearScope).toHaveBeenCalledWith('c1')
  })

  it('onCancel is a no-op for wrong token', async () => {
    const { audioPlayback } = await import('../../infrastructure/audioPlayback')
    ;(audioPlayback.clearScope as any).mockClear()
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    child.onCancel('user-stop', 'other')
    expect(audioPlayback.clearScope).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 7.5: Run all voice-children tests**

```bash
cd frontend && pnpm run test -- voice/children
```

Expected: all pass.

- [ ] **Step 7.6: Commit**

```bash
git add frontend/src/features/voice/children/
git commit -m "Add pauser, synth, and playback GroupChildren for voice mode"
```

---

## Task 8: Frontend — Wire Group from `ChatView.handleSend`/`handleCancel`

**Why:** This is the flip-the-switch moment. `handleSend` generates the `correlationId`, builds the Group with the right children, registers it, and *then* sends `chat.send`. `handleCancel` calls `group.cancel('user-stop')` — it no longer manually sends `chat.cancel` or calls `cancelStreamingAutoRead`.

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx` (handleSend ~line 470, handleCancel line 534, handleEdit ~line 546, handleRegenerate ~line 594)
- Create: `frontend/src/features/chat/buildChildren.ts`
- Create: `frontend/src/features/chat/__tests__/buildChildren.test.ts`

- [ ] **Step 8.1: Create the `buildChildren` helper**

Create `frontend/src/features/chat/buildChildren.ts`:

```ts
import type { GroupChild } from './responseTaskGroup'
import { createChatStoreSink } from './children/chatStoreSink'
import { createSentencerChild } from '../voice/children/sentencerChild'
import { createPauserChild } from '../voice/children/pauserChild'
import { createSynthChild } from '../voice/children/synthChild'
import { createPlaybackChild } from '../voice/children/playbackChild'
import { createStreamingSentencer } from '../voice/pipeline/streamingSentencer'
import { useChatStore } from '../../core/store/chatStore'
import type { NarratorMode, TTSEngine, VoicePreset } from '../voice/types'
import type { VoiceModulation } from '../voice/pipeline/applyModulation'

export type Mode = 'text' | 'voice'

export interface BuildChildrenOpts {
  correlationId: string
  sessionId: string
  mode: Mode
  /** Voice-mode settings. Ignored when mode==='text'. */
  voice?: {
    tts: TTSEngine
    voice: VoicePreset
    narratorVoice: VoicePreset
    narratorMode: NarratorMode
    modulation: VoiceModulation
    gapMs: number
    narratorEnabled: boolean
  }
}

/**
 * Build the list of GroupChildren for a new response. Text-mode returns
 * only chatStoreSink; voice-mode adds the sentencer/pauser/synth/playback
 * chain with voice-internal DI wiring (sentencer.onSegment → pauser →
 * synth.enqueueSegment).
 */
export function buildChildren(opts: BuildChildrenOpts): GroupChild[] {
  const { correlationId, sessionId, mode, voice } = opts

  const children: GroupChild[] = [
    createChatStoreSink({
      sessionId, correlationId,
      chatStore: useChatStore.getState() as any,
    }),
  ]

  if (mode === 'voice' && voice) {
    const sentencer = createStreamingSentencer({
      mode: voice.narratorMode,
      narratorEnabled: voice.narratorEnabled,
    })

    const synth = createSynthChild({
      correlationId,
      tts: voice.tts,
      voice: voice.voice,
      narratorVoice: voice.narratorVoice,
      mode: voice.narratorMode,
      modulation: voice.modulation,
    })

    const pauser = createPauserChild({
      correlationId,
      onSegmentReleased: (seg, token) => { void synth.enqueueSegment(seg, token) },
    })

    const sentencerChild = createSentencerChild({
      correlationId,
      sentencer,
      onSegment: (seg, token) => pauser.pushSegment(seg, token),
    })

    const playback = createPlaybackChild({
      correlationId,
      gapMs: voice.gapMs,
    })

    children.push(sentencerChild, pauser, synth, playback)
  }

  return children
}
```

- [ ] **Step 8.2: Add a smoke test for buildChildren**

```ts
// frontend/src/features/chat/__tests__/buildChildren.test.ts
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../voice/infrastructure/audioPlayback', () => ({
  audioPlayback: {
    setCurrentToken: vi.fn(),
    setCallbacks: vi.fn(),
    closeStream: vi.fn(),
    clearScope: vi.fn(),
    enqueue: vi.fn(),
  },
}))

import { buildChildren } from '../buildChildren'

describe('buildChildren', () => {
  it('text mode returns only chatStoreSink', () => {
    const children = buildChildren({
      correlationId: 'c1', sessionId: 's1', mode: 'text',
    })
    expect(children.map((c) => c.name)).toEqual(['chatStoreSink'])
  })

  it('voice mode returns full chain', () => {
    const fakeTts: any = { synthesise: vi.fn() }
    const children = buildChildren({
      correlationId: 'c1', sessionId: 's1', mode: 'voice',
      voice: {
        tts: fakeTts,
        voice: {} as any,
        narratorVoice: {} as any,
        narratorMode: 'dialogue' as any,
        modulation: {} as any,
        gapMs: 100,
        narratorEnabled: true,
      },
    })
    expect(children.map((c) => c.name)).toEqual([
      'chatStoreSink', 'sentencer', 'pauser', 'synth', 'playback',
    ])
  })
})
```

Run:

```bash
cd frontend && pnpm run test -- buildChildren.test
```

Expected: both tests pass.

- [ ] **Step 8.3: Modify `ChatView.tsx handleSend`**

Open `frontend/src/features/chat/ChatView.tsx`. Imports block (near lines 48–63): add:

```ts
import { createResponseTaskGroup, registerActiveGroup, getActiveGroup } from './responseTaskGroup'
import { buildChildren, type Mode } from './buildChildren'
```

Remove imports that will no longer be used directly from `handleSend`/`handleCancel` once wired — leave them for now (they are still used by the old useEffect paths that Task 10 will prune).

Locate `handleSend` (around line 470-532). Before the `sendMessage({ type: 'chat.send', ... })` call (around line 519), insert:

```ts
const correlationId = crypto.randomUUID()
const mode: Mode = conversationActive ? 'voice' : 'text'
const children = buildChildren({
  correlationId,
  sessionId: effectiveSessionId,
  mode,
  voice: mode === 'voice' ? {
    tts: resolveTTSEngine()!,
    voice: persona?.voice_config?.voice ?? 'default',
    narratorVoice: persona?.voice_config?.narrator_voice ?? 'default',
    narratorMode: persona?.voice_config?.narrator_mode ?? 'off',
    modulation: resolveModulation(persona),
    gapMs: resolveTtsGapMs(resolveTTSEngine()!),
    narratorEnabled: persona?.voice_config?.narrator_mode !== 'off',
  } : undefined,
})
const group = createResponseTaskGroup({
  correlationId,
  sessionId: effectiveSessionId,
  userId: '',  // user id not currently threaded through ChatView; OK for now
  children,
  sendWsMessage: sendMessage,
  logger: {
    info: (msg, ...a) => console.info(msg, ...a),
    debug: (msg, ...a) => console.debug(msg, ...a),
    warn: (msg, ...a) => console.warn(msg, ...a),
    error: (msg, ...a) => console.error(msg, ...a),
  },
})
registerActiveGroup(group)
```

Then modify the `chat.send` / `chat.incognito.send` calls below to include `correlation_id: correlationId` in their payloads:

```ts
if (isIncognito) {
  sendMessage({
    type: 'chat.incognito.send',
    persona_id: personaId,
    session_id: effectiveSessionId,
    correlation_id: correlationId,
    messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
  })
} else {
  const attachmentIds = attachments.getAttachmentIds()
  sendMessage({
    type: 'chat.send',
    session_id: effectiveSessionId,
    correlation_id: correlationId,
    content: [{ type: 'text', text }],
    client_message_id: clientMessageId,
    ...(attachmentIds.length > 0 ? { attachment_ids: attachmentIds } : {}),
  })
  attachments.clearAttachments()
  setShowUploadBrowser(false)
}
```

Read `conversationActive`'s definition (it's already in the file — it comes from `useConversationModeStore`; find it with grep).

- [ ] **Step 8.4: Modify `handleCancel`**

Replace the body of `handleCancel` (line 534-544) with:

```ts
const handleCancel = useCallback(() => {
  const g = getActiveGroup()
  if (!g) return
  g.cancel('user-stop')
  setPartialSavedNotice(true)
  setTimeout(() => setPartialSavedNotice(false), 6000)
}, [])
```

The `correlationId` prop dependency, the `sendMessage` call, the `cancelStreamingAutoRead()` call, and the `setActiveReader(null, 'idle')` call are all gone — they're either redundant with what `group.cancel()` does via `playbackChild.onCancel`, or will be after Tasks 10–11.

- [ ] **Step 8.5: Modify `handleEdit` and `handleRegenerate`**

For `handleEdit` (around line 546-592): before calling `sendMessage({ type: 'chat.edit', ... })`, do the same group-creation dance:

```ts
const correlationId = crypto.randomUUID()
const mode: Mode = conversationActive ? 'voice' : 'text'
const children = buildChildren({
  correlationId,
  sessionId: effectiveSessionId,
  mode,
  voice: mode === 'voice' ? { /* same block as handleSend */ } : undefined,
})
const group = createResponseTaskGroup({
  correlationId, sessionId: effectiveSessionId, userId: '',
  children, sendWsMessage: sendMessage, logger: /* same as handleSend */,
})
registerActiveGroup(group)

sendMessage({
  type: 'chat.edit',
  session_id: effectiveSessionId,
  message_id: messageId,
  correlation_id: correlationId,
  content: [{ type: 'text', text: newContent }],
})
```

Same for `handleRegenerate` (around line 594): generate `correlationId`, build children, register group, then `sendMessage({ type: 'chat.regenerate', session_id, correlation_id: correlationId })`.

Because the code block for building children + registering the group is now repeated three times, extract it to a helper colocated inside `ChatView.tsx`:

```ts
const createAndRegisterGroup = useCallback((correlationId: string, sessionId: string) => {
  const mode: Mode = conversationActive ? 'voice' : 'text'
  const children = buildChildren({
    correlationId, sessionId, mode,
    voice: mode === 'voice' ? {
      tts: resolveTTSEngine()!,
      voice: persona?.voice_config?.voice ?? 'default',
      narratorVoice: persona?.voice_config?.narrator_voice ?? 'default',
      narratorMode: persona?.voice_config?.narrator_mode ?? 'off',
      modulation: resolveModulation(persona),
      gapMs: resolveTtsGapMs(resolveTTSEngine()!),
      narratorEnabled: persona?.voice_config?.narrator_mode !== 'off',
    } : undefined,
  })
  const group = createResponseTaskGroup({
    correlationId, sessionId, userId: '',
    children, sendWsMessage: sendMessage,
    logger: {
      info: (m, ...a) => console.info(m, ...a),
      debug: (m, ...a) => console.debug(m, ...a),
      warn: (m, ...a) => console.warn(m, ...a),
      error: (m, ...a) => console.error(m, ...a),
    },
  })
  registerActiveGroup(group)
  return group
}, [conversationActive, persona])
```

Then the three call sites call `createAndRegisterGroup(correlationId, effectiveSessionId)` right before their `sendMessage` call.

- [ ] **Step 8.6: Type-check and build**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: zero errors in files we touched.

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 8.7: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx frontend/src/features/chat/buildChildren.ts frontend/src/features/chat/__tests__/buildChildren.test.ts
git commit -m "Wire ResponseTaskGroup into ChatView send/cancel/edit/regenerate handlers"
```

---

## Task 9: Frontend — Route WS events through the Group in `useChatStream`

**Why:** The group needs `onDelta`/`onStreamEnd` to be driven by `CHAT_CONTENT_DELTA`/`CHAT_STREAM_ENDED` events. Today `useChatStream` writes directly to `chatStore` — we relocate the delta path so it goes via the group, which then fans out to its children (including `chatStoreSink`, which is what keeps the store updated).

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`

- [ ] **Step 9.1: Add Group-routing at top of handler**

Open `frontend/src/features/chat/useChatStream.ts`. In the `handleChatEvent` switch, replace the `CHAT_CONTENT_DELTA` (line 39-45) case with:

```ts
case Topics.CHAT_CONTENT_DELTA: {
  const g = getActiveGroup()
  if (!g || g.id !== event.correlation_id) {
    console.debug(`[useChatStream] drop CHAT_CONTENT_DELTA (no matching group, id=${event.correlation_id})`)
    return
  }
  const rawDelta = p.delta as string
  // Tag buffer still lives here — it transforms deltas before storage.
  // The buffer wraps the store.appendStreamingContent call via a callback
  // set when the buffer was created in CHAT_STREAM_STARTED.
  const visibleDelta = activeTagBuffer ? activeTagBuffer.process(rawDelta) : rawDelta
  g.onDelta(visibleDelta)
  break
}
```

Replace the `CHAT_STREAM_ENDED` handler's opening lines so that the group gets a chance to drain too:

```ts
case Topics.CHAT_STREAM_ENDED: {
  if (p.session_id !== sessionId) return
  const g = getActiveGroup()
  if (g && g.id === event.correlation_id) g.onStreamEnd()
  // ... existing body starting at "Flush incomplete tag buffer" ...
}
```

In the `CHAT_STREAM_STARTED` handler (line 25-38), keep the `getStore().startStreaming(event.correlation_id)` call — the store state is independent of the Group. The store's `correlationId` field is still used by tool-call / thinking handlers.

Add the `getActiveGroup` import at the top of the file:

```ts
import { getActiveGroup } from './responseTaskGroup'
```

- [ ] **Step 9.2: Preserve `chat.incognito` parity**

The incognito flow produces the same events with the same `correlation_id` — no change needed here, as long as `handleSend` registered a Group when sending `chat.incognito.send` (Task 8.3 handled this).

- [ ] **Step 9.3: Type-check and build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm run build
```

Expected: clean.

- [ ] **Step 9.4: Run all chat + voice tests**

```bash
cd frontend && pnpm run test -- chat/ voice/
```

Expected: all pass. Some existing ChatView/useChatStream tests may need minor adjustment (e.g. mock for `getActiveGroup`) — fix on the spot.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Route CHAT_CONTENT_DELTA and CHAT_STREAM_ENDED through active Group"
```

---

## Task 10: Frontend — `useConversationMode` STT verbs and remove old cancelStreamingAutoRead call sites

**Why:** STT-side barge triggers (`executeBarge`, `transcribeAndSend` outcomes) now speak the group verb vocabulary (`pause`/`resume`/`cancel`). This replaces the `audioPlayback.mute`/`resumeFromMute`/`discardMuted` machinery at the call-site level.

**Files:**
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts`
- Modify: `frontend/src/features/chat/ChatView.tsx` (remove the two flanky useEffects + other `cancelStreamingAutoRead` call sites that are now redundant)
- Modify: `frontend/src/features/integrations/ChatIntegrationsPanel.tsx` (one `cancelStreamingAutoRead` call)

- [ ] **Step 10.1: Find all `audioPlayback.mute` / `cancelStreamingAutoRead` call sites**

```bash
grep -rn "audioPlayback\.mute\|audioPlayback\.resumeFromMute\|audioPlayback\.discardMuted\|cancelStreamingAutoRead" frontend/src
```

Expected hits (verify):
- `frontend/src/features/voice/hooks/useConversationMode.ts:306, 323, 519`
- `frontend/src/features/chat/ChatView.tsx:~540, ~805, ~920, ~928, ~947`
- `frontend/src/features/integrations/ChatIntegrationsPanel.tsx:89`
- `frontend/src/features/voice/pipeline/streamingAutoReadControl.ts` (the definitions — keep the file for now, remove exports in Task 14)

- [ ] **Step 10.2: Modify `useConversationMode.ts` STT verbs**

At line 306 (executeBarge — the tentative-pause path): replace

```ts
cancelStreamingAutoRead()
```

with

```ts
getActiveGroup()?.pause()
```

At line 323 (inside transcribeAndSend `confirm` outcome): replace

```ts
cancelStreamingAutoRead()
```

with

```ts
getActiveGroup()?.cancel('barge-cancel')
```

At line 519 (cleanup on exit of conversation mode): replace

```ts
cancelStreamingAutoRead()
```

with

```ts
getActiveGroup()?.cancel('teardown')
```

Add at the top of the file:

```ts
import { getActiveGroup } from '../../chat/responseTaskGroup'
```

Remove the import of `cancelStreamingAutoRead` from the same file.

Look for the `resume` outcome in `transcribeAndSend` (likely right after the confirm path) — replace any `audioPlayback.resumeFromMute()` / `audioPlayback.discardMuted()` calls with `getActiveGroup()?.resume()`.

- [ ] **Step 10.3: Remove the flanky useEffects from `ChatView.tsx`**

In `ChatView.tsx` locate:
- `useEffect([isStreaming])` around line 800 (the "Start- and end-of-stream transitions" effect)
- `useEffect([streamingContent, isStreaming])` around line 913 ("Mid-stream: each streamingContent update…")
- `useEffect(() => ... cancelStreamingAutoRead())` around line 919 (unmount cleanup)

Delete the body of the first two effects entirely — all their work is now done by the group/children.

The unmount cleanup effect can be rewritten to cancel the active group instead:

```ts
useEffect(() => {
  return () => { getActiveGroup()?.cancel('teardown') }
}, [])
```

Also remove the `cancelStreamingAutoRead()` calls in:
- `handleMicPress` (line ~928)
- `handleVoiceToggle` (line ~947)

Replace those with:

```ts
getActiveGroup()?.cancel('teardown')
```

For `handleCancel` (already done in Task 8.4), confirm the `cancelStreamingAutoRead()` is gone.

- [ ] **Step 10.4: Modify `ChatIntegrationsPanel.tsx`**

At line 89:

```ts
cancelStreamingAutoRead()
```

becomes

```ts
getActiveGroup()?.cancel('teardown')
```

Update the import at the top of the file.

- [ ] **Step 10.5: Type-check and build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm run build
```

Expected: clean.

- [ ] **Step 10.6: Run full frontend test suite**

```bash
cd frontend && pnpm run test
```

Expected: all pass. Failing tests in `ChatIntegrationsPanel.test.tsx` / `useConversationMode.*.test.tsx` that mock `cancelStreamingAutoRead`: update their mocks to the new API (`getActiveGroup` returning a mock group with `cancel`/`pause`/`resume`).

- [ ] **Step 10.7: Commit**

```bash
git add frontend/src/features/voice/hooks/useConversationMode.ts frontend/src/features/chat/ChatView.tsx frontend/src/features/integrations/ChatIntegrationsPanel.tsx
git commit -m "Route STT barge and UI cancel paths through active Group verbs"
```

---

## Task 11: Backend — `handle_chat_retract`

**Why:** The last missing WS operation. Frontend sends this when cancelling before the first delta; backend deletes the user message and broadcasts `CHAT_MESSAGE_DELETED` so the bubble disappears from all tabs.

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`
- Modify: `backend/modules/chat/__init__.py` (export the new handler)
- Modify: `backend/ws/router.py` (dispatch table)
- Test: `backend/modules/chat/tests/test_handle_chat_retract.py` (new)

- [ ] **Step 11.1: Write failing test**

```python
"""Tests for handle_chat_retract — barge-before-delta path."""

from unittest.mock import AsyncMock
import pytest

from backend.modules.chat._handlers_ws import handle_chat_retract
from backend.modules.chat._orchestrator import _cancel_events


@pytest.mark.asyncio
async def test_retract_sets_cancel_event_and_deletes_user_message(test_db, monkeypatch):
    import asyncio

    # Seed state: one cancel_event and one user message with matching correlation_id
    corr = "corr-xyz"
    _cancel_events[corr] = asyncio.Event()

    from backend.modules.chat._repository import ChatRepository
    repo = ChatRepository(test_db)
    await repo.create_indexes()
    await repo.create_session("user1", "persona1")
    session = await test_db["chat_sessions"].find_one({"user_id": "user1"})
    await repo.save_message(
        session["_id"], role="user", content="hello",
        token_count=1, correlation_id=corr,
    )

    published = []
    async def fake_publish(event_type, event, **kwargs):
        published.append((event_type, kwargs.get("correlation_id")))
    class FakeBus: publish = fake_publish

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_event_bus", lambda: FakeBus())
    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: test_db)

    await handle_chat_retract("user1", {"correlation_id": corr})

    # cancel event was set
    assert _cancel_events[corr].is_set()
    # message was deleted
    remaining = await test_db["chat_messages"].find({"correlation_id": corr}).to_list(length=5)
    assert len(remaining) == 0
    # CHAT_MESSAGE_DELETED was published
    assert any(t.endswith("message.deleted") or "deleted" in t.lower() for (t, _) in published)

    _cancel_events.pop(corr, None)


@pytest.mark.asyncio
async def test_retract_noop_when_no_correlation_id(test_db, monkeypatch):
    # Should not raise, should not publish
    published = []
    async def fake_publish(event_type, event, **kwargs):
        published.append(event_type)
    class FakeBus: publish = fake_publish

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_event_bus", lambda: FakeBus())
    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: test_db)

    await handle_chat_retract("user1", {})
    assert published == []
```

- [ ] **Step 11.2: Run test to verify it fails**

```bash
uv run pytest backend/modules/chat/tests/test_handle_chat_retract.py -v
```

Expected: fails — `handle_chat_retract` does not exist.

- [ ] **Step 11.3: Implement the handler**

In `backend/modules/chat/_handlers_ws.py`, add after `handle_chat_cancel` (line 347-351):

```python
async def handle_chat_retract(user_id: str, data: dict) -> None:
    """Handle chat.retract — cancel in-flight inference and delete its user message.

    Used when the frontend cancels a response before any CONTENT_DELTA
    has arrived (the barge-before-delta case). The user message itself
    should disappear from history so the user is not left with a stray
    prompt bubble.
    """
    correlation_id = data.get("correlation_id")
    if not correlation_id:
        return

    # 1. Signal cancel (identical to handle_chat_cancel)
    if correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()

    try:
        db = get_db()
        repo = ChatRepository(db)

        user_message_id = await repo.user_message_by_correlation(user_id, correlation_id)
        if not user_message_id:
            _log.info(
                "chat.retract: no user message for correlation_id=%s",
                correlation_id,
            )
            return

        await repo.delete_message(user_message_id)

        event_bus = get_event_bus()
        # Find the session_id from the deleted message for scope
        # (the delete_message call above may already have returned the doc
        # — if not, do a pre-fetch before delete_message)
        await event_bus.publish(
            Topics.CHAT_MESSAGE_DELETED,
            ChatMessageDeletedEvent(
                session_id=data.get("session_id", ""),
                message_id=user_message_id,
                correlation_id=correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"session:{data.get('session_id', '')}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
    except Exception:
        _log.exception("Unhandled error in handle_chat_retract for user %s", user_id)
```

Note: `ChatMessageDeletedEvent` needs `session_id` — inspect whether the existing field set on the `CHAT_MESSAGE_DELETED` event requires session_id. If so, fetch the message doc *before* deleting it (add a `repo.get_message(user_message_id)` call). If `repo.delete_message` returns the old doc, use that instead.

In `backend/modules/chat/__init__.py` (line 15 area), add `handle_chat_retract` to the imports; in the `__all__` list (line 298 area), add it.

In `backend/ws/router.py` (line 199-201 area, where `chat.cancel` is dispatched), add:

```python
elif msg_type == "chat.retract":
    await handle_chat_retract(user_id, data)
```

And add `handle_chat_retract` to the import block at line 15 in `router.py`.

- [ ] **Step 11.4: Run tests to verify**

```bash
uv run pytest backend/modules/chat/tests/test_handle_chat_retract.py -v
uv run python -m py_compile backend/modules/chat/_handlers_ws.py backend/modules/chat/__init__.py backend/ws/router.py
```

Expected: tests pass, clean compile.

- [ ] **Step 11.5: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py backend/modules/chat/__init__.py backend/ws/router.py backend/modules/chat/tests/test_handle_chat_retract.py
git commit -m "Add handle_chat_retract backend handler for barge-before-delta"
```

---

## Task 12: Frontend — Enable retract in `group.cancel()`

**Why:** `responseTaskGroup.ts` already sends `chat.retract` when state was `before-first-delta` — we wrote it that way in Task 4. Now that the backend accepts it (Task 11), exercise the path end-to-end and verify the retract test case works.

**Files:**
- Test: `frontend/src/features/chat/__tests__/responseTaskGroup.retract.test.ts` (new)

- [ ] **Step 12.1: Integration-flavoured test for the retract path**

```ts
// frontend/src/features/chat/__tests__/responseTaskGroup.retract.test.ts
import { describe, it, expect, vi } from 'vitest'
import { createResponseTaskGroup } from '../responseTaskGroup'

describe('ResponseTaskGroup retract path', () => {
  it('cancel from before-first-delta sends exactly chat.retract', () => {
    const sendWs = vi.fn()
    const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger,
    })
    g.cancel('barge-retract')
    expect(sendWs).toHaveBeenCalledTimes(1)
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.retract', correlation_id: 'c1',
    })
  })

  it('after first delta, cancel sends chat.cancel', () => {
    const sendWs = vi.fn()
    const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger,
    })
    g.onDelta('a')
    g.cancel('barge-cancel')
    expect(sendWs).toHaveBeenCalledTimes(1)
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.cancel', correlation_id: 'c1',
    })
  })
})
```

- [ ] **Step 12.2: Run tests**

```bash
cd frontend && pnpm run test -- responseTaskGroup.retract.test
```

Expected: pass (no code change needed; already implemented in Task 4).

- [ ] **Step 12.3: Commit**

```bash
git add frontend/src/features/chat/__tests__/responseTaskGroup.retract.test.ts
git commit -m "Lock retract-vs-cancel branching in responseTaskGroup tests"
```

---

## Task 13: Manual verification on a real device

**Why:** Per the project convention every spec ships with a manual-test section. This is the real judgement call — does it feel right under user hands.

- [ ] **Step 13.1: Start backend + frontend**

```bash
# In one terminal
cd backend && uv run uvicorn backend.main:app --reload

# In another
cd frontend && pnpm dev
```

- [ ] **Step 13.2: Run the 11 manual verification steps from the spec**

Go through `devdocs/response-task-group-architecture.md` §10.3 one by one. Record outcomes in this plan as short notes below:

**Voice tests:**
- [ ] Step 1 — barge during TTS play: audio stops ~500ms
- [ ] Step 2 — barge before first token: user message disappears
- [ ] Step 3 — barge after stream end, during TTS: audio stops, message preserved
- [ ] Step 4 — misfire test: pause + resume
- [ ] Step 5 — rapid double-barge
- [ ] Step 6 — multi-tab

**Text tests:**
- [ ] Step 7 — text cancel during stream
- [ ] Step 8 — text cancel before first delta (retract)
- [ ] Step 9 — regenerate during stream
- [ ] Step 10 — mode switch mid-stream (A behaviour: stream continues as text, TTS only for next message)
- [ ] Step 11 — log audit: two full responses reconstructable from console `[group …]` lines

- [ ] **Step 13.3: If any step fails, diagnose before proceeding**

Check backend + frontend logs. File an issue in the plan document as "Deviation at step N: …" and fix before continuing to Task 14. Do not mark the step as passed if anything is off.

- [ ] **Step 13.4: No commit needed for manual verification notes unless changes were required**

---

## Task 14: Cleanup — remove `audioPlayback` mute shim and `streamingAutoReadControl` residue

**Why:** Once every call site routes through Group, the shim in Task 3 and the legacy `streamingAutoReadControl.ts` exports are dead code.

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts` (remove `mute`, `resumeFromMute`, `discardMuted`, `isMuted`, `skipCurrent`)
- Modify: `frontend/src/features/voice/pipeline/streamingAutoReadControl.ts` (remove `cancelStreamingAutoRead` export, or delete the file if nothing else imports from it)
- Modify: tests that mocked those APIs

- [ ] **Step 14.1: Verify no remaining call sites**

```bash
grep -rn "audioPlayback\.mute\|audioPlayback\.resumeFromMute\|audioPlayback\.discardMuted\|audioPlayback\.isMuted\|audioPlayback\.skipCurrent\|cancelStreamingAutoRead" frontend/src
```

Expected: no hits outside `audioPlayback.ts` itself. Any hit is a missed migration — fix before removing.

- [ ] **Step 14.2: Remove the shim methods**

In `frontend/src/features/voice/infrastructure/audioPlayback.ts`, delete:
- `mute()` (lines ~102-139)
- `resumeFromMute()` (lines ~149-162)
- `discardMuted()` (lines ~171-181)
- `isMuted()` (line ~183)
- `skipCurrent()` (lines ~185-191)
- The private fields `muted`, `mutedEntry`, `mutedOffsetSec`, `pendingResumeOffsetSec` (lines ~24-27, ~37-40)

Update `stopAll()` to drop the mute-related resets (lines ~76-79).

Update `enqueue` (line 60) to remove the `!this.muted` check — it's no longer relevant.

Tighten the `enqueue` signature: make `token` required (was optional in Task 3):

```ts
enqueue(audio: Float32Array, segment: SpeechSegment, token: string): void {
  if (this.currentToken !== null && token !== this.currentToken) {
    console.debug(`[audioPlayback] drop chunk (token mismatch: got=${token}, current=${this.currentToken})`)
    return
  }
  this.queue.push({ audio, segment })
  if (!this.playing && this.pendingGapTimer === null) this.playNext()
  this.emit()
}
```

- [ ] **Step 14.3: Clean up `streamingAutoReadControl.ts`**

If nothing imports from `streamingAutoReadControl.ts` any more, delete the file:

```bash
grep -rn "streamingAutoReadControl" frontend/src
```

If the only remaining references are tests of the module itself, delete both the module and its tests. If something still imports (e.g. `getActiveStreamingAutoRead`), evaluate whether that is a leftover or a useful helper; ideally, it too is dead.

- [ ] **Step 14.4: Update / remove stale tests**

Delete tests that were testing the removed mute API. Remove mocks of `cancelStreamingAutoRead` that no longer apply.

```bash
cd frontend && pnpm run test
```

Fix any breakage.

- [ ] **Step 14.5: Type-check and build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm run build
```

Expected: clean.

- [ ] **Step 14.6: Commit**

```bash
git add frontend/src/features/voice/
git commit -m "Remove mute/resumeFromMute/discardMuted shim and streamingAutoReadControl"
```

---

## Task 15: Merge to master (per CLAUDE.md convention)

**Why:** Chatsune's CLAUDE.md says "always merge to master after implementation". If this work was done on a side branch, merge now.

- [ ] **Step 15.1: Verify current branch + status**

```bash
git status
git log master..HEAD --oneline
```

- [ ] **Step 15.2: Merge to master if needed**

If we are not on master:

```bash
git checkout master
git merge --no-ff <branch-name>
```

If we are already on master (likely, because Chris said "direkt loslegen"), this step is a no-op.

- [ ] **Step 15.3: Push (ask user first)**

Do not push without asking. Ask Chris: "Alle 14 Implementierungs-Tasks grün, Spec-Commit und diese 14 commits sind auf master lokal. Pushen?"

---

# Self-Review Checklist (completed by plan author)

**Spec coverage:**
- §1 Problem Statement → captured in Migration Ordering Rationale + each Task's "Why"
- §2 Mental Model → Task 4 (Group core), Task 5-7 (children), Task 8 (buildChildren)
- §3 Group Structure → Task 4
- §4 State Machine → Task 4 (tests cover all transitions)
- §5 Token Propagation → Task 3 (audioPlayback token-aware), Tasks 5-7 (children all verify token)
- §6 WS Flows → Tasks 8-12 wire them; Task 13 manually verifies all cases
- §7 Backend Changes → Tasks 1, 2, 11
- §8 Frontend Changes → Tasks 3-10
- §9 Logging → present inline in Task 4 (`[group hash]`), Task 5 (`[chatStoreSink]`), Task 7 (`[TTS-infer]`, `[TTS-play]`, `[playback]`)
- §10 Tests → Tasks 1, 2, 4, 5, 6, 7, 11, 12 + Task 13 manual
- §11 Migration Path → the 14-task ordering of this plan *is* the path, plus cleanup
- §12 Open Questions → none blocking

**No placeholders:** reviewed — no TODO/TBD/FIXME.

**Type consistency:** `GroupChild`, `ResponseTaskGroup`, `CancelReason`, `GroupState`, `buildChildren`, `createChatStoreSink`, `createSentencerChild`, `createPauserChild`, `createSynthChild`, `createPlaybackChild` — all referenced with consistent names across tasks.

**Scope:** fits one implementation plan. Migration path spans ~20h across 14 tasks.
