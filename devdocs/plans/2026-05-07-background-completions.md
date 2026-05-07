# Background Completions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inferences finish and persist regardless of persona switches, navigation, tab close, reload, or WS disconnect; only an explicit Stop button or a new send in the same session cancels them.

**Architecture:** Cancel granularity moves from per-user to per-session on the backend (`cancel_inflight_for_session` replaces three `cancel_all_for_user` call sites in handlers; the WS disconnect cleanup no longer cancels inferences). Disconnect-driven memory-extraction triggers shift from a 10-second grace timer to "user has no connections AND no inflight inferences" at every inference cleanup. The frontend keeps a streaming-state map keyed by session id and a multi-group registry keyed by session id, so multiple inferences can stream concurrently into different sessions; a sidebar pulse-dot indicator and a right-click "Stop generation" menu give the user visibility and control over background streams.

**Tech Stack:** FastAPI / Python 3.12, asyncio, MongoDB, Redis Streams, React 18 / Vite / TypeScript, Zustand, Tailwind.

**Spec:** `devdocs/specs/2026-05-07-background-completions-design.md`

**Branch:** `feat/background-completions` (already created).

---

## Conventions for All Backend Tests

- Every backend pytest invocation prepends `PYTHONPATH=<repo-root>` (the repo's `pyproject.toml` lives in `backend/`, so pytest's rootdir resolves there and the top-level `shared/` import path needs help).
- The four MongoDB-dependent test files are excluded on the host. None of the new tests in this plan touch MongoDB; they exercise in-memory cancel registries, asyncio locks, and Zustand stores.
- Run from the repo root.

## Conventions for All Frontend Tests

- `pnpm vitest run <path>` for a single file; `pnpm vitest run` for the suite.
- After all frontend changes in a task: `pnpm run build` (this is the canonical strict-build check; `tsc --noEmit` alone misses some errors that the build catches).

---

## Task 1: Backend — Session-Scoped Cancel Registry

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py:111-186` (replace `_cancel_user_ids`, add `cancel_inflight_for_session`, add `_user_has_inflight`)
- Modify: `backend/modules/chat/__init__.py:24` (export new symbol)
- Test: `backend/tests/modules/chat/test_orchestrator_cancel.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/chat/test_orchestrator_cancel.py`:

```python
"""Tests for session-scoped cancel registry in chat._orchestrator."""

import asyncio
import pytest

from backend.modules.chat._orchestrator import (
    _cancel_events,
    _inflight,
    cancel_all_for_user,
    cancel_inflight_for_session,
    request_cancel,
    _user_has_inflight,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    _cancel_events.clear()
    _inflight.clear()
    yield
    _cancel_events.clear()
    _inflight.clear()


def _register(correlation_id: str, user_id: str, session_id: str) -> asyncio.Event:
    event = asyncio.Event()
    _cancel_events[correlation_id] = event
    _inflight[correlation_id] = (user_id, session_id)
    return event


@pytest.mark.asyncio
async def test_cancel_inflight_for_session_targets_only_matching_session():
    e1 = _register("cor-1", "user-a", "session-x")
    e2 = _register("cor-2", "user-a", "session-y")
    e3 = _register("cor-3", "user-b", "session-x")

    cancelled = await cancel_inflight_for_session("user-a", "session-x")

    assert cancelled == 1
    assert e1.is_set()
    assert not e2.is_set()
    assert not e3.is_set()


@pytest.mark.asyncio
async def test_cancel_all_for_user_still_works_for_admin_use():
    e1 = _register("cor-1", "user-a", "session-x")
    e2 = _register("cor-2", "user-a", "session-y")
    e3 = _register("cor-3", "user-b", "session-x")

    cancelled = await cancel_all_for_user("user-a")

    assert cancelled == 2
    assert e1.is_set()
    assert e2.is_set()
    assert not e3.is_set()


@pytest.mark.asyncio
async def test_user_has_inflight_returns_true_when_any_correlation_present():
    assert _user_has_inflight("user-a") is False
    _register("cor-1", "user-a", "session-x")
    assert _user_has_inflight("user-a") is True
    assert _user_has_inflight("user-b") is False


def test_request_cancel_with_user_id_filter_rejects_other_user():
    _register("cor-1", "user-a", "session-x")
    fired = request_cancel("cor-1", user_id="user-b")
    assert fired is False
    assert not _cancel_events["cor-1"].is_set()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
PYTHONPATH=. uv run pytest backend/tests/modules/chat/test_orchestrator_cancel.py -v
```

Expected: FAIL with `ImportError: cannot import name '_inflight'` and `cannot import name 'cancel_inflight_for_session'`.

- [ ] **Step 3: Implement `_inflight` registry and `cancel_inflight_for_session`**

In `backend/modules/chat/_orchestrator.py`, replace lines 111-117 (the `_cancel_events` declaration plus the `_cancel_user_ids` mapping) with:

```python
# Active cancel events keyed by correlation_id
_cancel_events: dict[str, asyncio.Event] = {}

# Maps correlation_id -> (user_id, session_id) so cancel_inflight_for_session
# can filter in-flight inferences by owner+session, and so the disconnect-
# extraction anchor (Task 4) can answer "does this user have any inflight?".
# Written by run_inference and handle_incognito_send, cleaned up in their
# respective finally blocks.
_inflight: dict[str, tuple[str, str]] = {}
```

Then update `request_cancel` (lines 142-158) to read from `_inflight` instead of `_cancel_user_ids`:

```python
def request_cancel(correlation_id: str, user_id: str | None = None) -> bool:
    """Signal a correlation cancel now, or remember it until registration.

    Returns True if an already-registered inference was signalled, False if a
    pending tombstone was stored.
    """
    if not correlation_id:
        return False
    event = _cancel_events.get(correlation_id)
    if event is not None:
        owner_session = _inflight.get(correlation_id)
        owner = owner_session[0] if owner_session else None
        if user_id is None or owner is None or owner == user_id:
            event.set()
            return True
    _prune_pending_cancels()
    _pending_cancels[correlation_id] = (user_id, time.monotonic())
    return False
```

Replace `cancel_all_for_user` (lines 175-186) with the new pair plus the helper:

```python
async def cancel_all_for_user(user_id: str) -> int:
    """Cancel every in-flight inference belonging to the given user.

    Retained for tests and admin tooling. The WS-disconnect cleanup path
    no longer calls this — it is replaced by per-session granularity at
    the chat-handler layer.
    """
    targets = [cid for cid, (uid, _sid) in _inflight.items() if uid == user_id]
    for cid in targets:
        event = _cancel_events.get(cid)
        if event is not None:
            event.set()
    return len(targets)


async def cancel_inflight_for_session(user_id: str, session_id: str) -> int:
    """Cancel every in-flight inference belonging to (user_id, session_id).

    Used by chat.send / chat.edit / chat.regenerate to enforce the
    per-session single-stream policy: a fresh user action in the same
    session supersedes the running answer; cross-session activity does
    not.
    """
    targets = [
        cid for cid, (uid, sid) in _inflight.items()
        if uid == user_id and sid == session_id
    ]
    for cid in targets:
        event = _cancel_events.get(cid)
        if event is not None:
            event.set()
    return len(targets)


def _user_has_inflight(user_id: str) -> bool:
    """True if at least one inflight inference exists for this user.

    Read by the disconnect-extraction anchor (Task 4) so the trigger
    fires only when the user is offline AND has no work pending.
    """
    return any(uid == user_id for uid, _sid in _inflight.values())
```

- [ ] **Step 4: Update every write site of the old `_cancel_user_ids` mapping**

Find every assignment to `_cancel_user_ids` in `_orchestrator.py`:

```bash
rg -n "_cancel_user_ids" backend/modules/chat/_orchestrator.py
```

There are write sites in `run_inference` (registration and finally cleanup) and in `handle_incognito_send`. For each:

- Replace `_cancel_user_ids[correlation_id] = user_id` with `_inflight[correlation_id] = (user_id, session_id)`. The session id is in the local scope at every call site (it is the inference's target session).
- Replace `_cancel_user_ids.pop(correlation_id, None)` with `_inflight.pop(correlation_id, None)`.

Search for the `_consume_pending_cancel` use too — it does not need a session id, so its signature stays. But its body:

```python
def _consume_pending_cancel(correlation_id: str, user_id: str) -> bool:
    item = _pending_cancels.get(correlation_id)
    if not item:
        return False
    owner, ts = item
    if time.monotonic() - ts > _PENDING_CANCEL_TTL_SECONDS:
        _pending_cancels.pop(correlation_id, None)
        return False
    if owner is not None and owner != user_id:
        return False
    _pending_cancels.pop(correlation_id, None)
    return True
```

…stays unchanged (it only validates ownership of the pending tombstone).

Also: look for any imports of `_cancel_user_ids` outside this file:

```bash
rg -n "_cancel_user_ids" backend/
```

`_handlers_ws.py:16` imports it. Replace that import with `_inflight`. The handler does not currently read it directly (only the cancel function does), but the import line must be updated for type-checks.

- [ ] **Step 5: Update the public re-export**

In `backend/modules/chat/__init__.py:24`, update the `cancel_all_for_user` import to also expose `cancel_inflight_for_session`:

```python
from backend.modules.chat._orchestrator import (
    ...,
    cancel_all_for_user,
    cancel_inflight_for_session,
    ...,
)
```

And add it to the `__all__` list near the bottom of that file (around line 438).

- [ ] **Step 6: Run tests to verify they pass**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/chat/test_orchestrator_cancel.py -v
```

Expected: all four tests pass.

- [ ] **Step 7: Run any pre-existing orchestrator tests to verify no regression**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/chat/ -v --ignore=backend/tests/modules/chat/test_repository.py --ignore=backend/tests/modules/chat/test_handlers_ws_send.py --ignore=backend/tests/modules/chat/test_handlers_ws_edit.py --ignore=backend/tests/modules/chat/test_handlers_ws_regenerate.py
```

(The four `--ignore` paths are the MongoDB-dependent files. Skip any that do not exist; pytest tolerates `--ignore` for missing paths.)

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/chat/__init__.py backend/modules/chat/_handlers_ws.py backend/tests/modules/chat/test_orchestrator_cancel.py
git commit -m "Add session-scoped cancel registry to chat orchestrator"
```

---

## Task 2: Backend — Handlers Use Session-Scoped Cancel

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py:230, 431, 524` (three call sites)

- [ ] **Step 1: Replace the three `cancel_all_for_user` call sites**

In `backend/modules/chat/_handlers_ws.py`, locate each occurrence of `cancel_all_for_user(user_id)` inside `handle_chat_send`, `handle_chat_edit`, and `handle_chat_regenerate`. The three blocks look identical except for the log line. Replace each with:

```python
        # Per-session single-stream policy: a new user action cancels
        # the in-flight inference for *this session only*. Inferences
        # in other sessions (e.g. the user's other persona) keep
        # running in the background and persist when they finish.
        cancelled = await cancel_inflight_for_session(user_id, session_id)
        if cancelled:
            _log.info(
                "chat.<verb> cancelled %d in-flight inference(s) for session=%s user=%s",
                cancelled, session_id, user_id,
            )
```

…with `<verb>` being `send`, `edit`, or `regenerate` respectively in each log line.

Update the import at `_handlers_ws.py:14-23` to add `cancel_inflight_for_session`:

```python
from backend.modules.chat._orchestrator import (
    _cancel_events,
    _inflight,
    _consume_pending_cancel,
    _make_tool_executor,
    cancel_all_for_user,
    cancel_inflight_for_session,
    emit_session_expired,
    request_cancel,
    run_inference,
    track_extraction_trigger,
)
```

The `cancel_all_for_user` import stays (some other code path may still reference it; the linter will tell us if not).

- [ ] **Step 2: Verify no other handler still calls `cancel_all_for_user`**

```bash
rg -n "cancel_all_for_user" backend/modules/chat/_handlers_ws.py
```

Expected: zero matches in this file. If any remain, update them with the same pattern.

- [ ] **Step 3: Write a behavioural test for the new same-session-only semantics**

Append to `backend/tests/modules/chat/test_orchestrator_cancel.py`:

```python
@pytest.mark.asyncio
async def test_concurrent_sessions_do_not_cancel_each_other():
    """User has two inflight inferences in two different sessions;
    cancelling for one session must leave the other untouched."""
    e_a = _register("cor-a", "user-a", "session-A")
    e_b = _register("cor-b", "user-a", "session-B")

    n = await cancel_inflight_for_session("user-a", "session-A")

    assert n == 1
    assert e_a.is_set()
    assert not e_b.is_set()
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/chat/test_orchestrator_cancel.py -v
```

Expected: all five tests pass (four from Task 1 plus the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py backend/tests/modules/chat/test_orchestrator_cancel.py
git commit -m "Switch chat handlers to per-session cancel granularity"
```

---

## Task 3: Backend — WS-Disconnect No Longer Cancels Inferences

**Files:**
- Modify: `backend/ws/router.py:281-318` (delayed-disconnect cleanup)
- Test: `backend/tests/ws/test_disconnect_cleanup.py` (new)

- [ ] **Step 1: Write a failing test for the new behaviour**

Create `backend/tests/ws/test_disconnect_cleanup.py`:

```python
"""Tests that the WS-disconnect cleanup no longer cancels inflight inferences."""

import asyncio
import pytest

from backend.modules.chat._orchestrator import (
    _cancel_events,
    _inflight,
)
from backend.ws.router import _disconnect_cleanup_for_test  # exposed by Task 3


@pytest.fixture(autouse=True)
def _clear_registry():
    _cancel_events.clear()
    _inflight.clear()
    yield
    _cancel_events.clear()
    _inflight.clear()


@pytest.mark.asyncio
async def test_disconnect_cleanup_does_not_cancel_inflight():
    event = asyncio.Event()
    _cancel_events["cor-1"] = event
    _inflight["cor-1"] = ("user-a", "session-x")

    # Simulate disconnect with no reconnect: inference must keep running.
    await _disconnect_cleanup_for_test(
        user_id="user-a",
        connection_id="conn-1",
        has_reconnect=False,
    )

    assert not event.is_set(), "inference must NOT be cancelled by disconnect"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONPATH=. uv run pytest backend/tests/ws/test_disconnect_cleanup.py -v
```

Expected: FAIL with `cannot import name '_disconnect_cleanup_for_test'`.

- [ ] **Step 3: Refactor `_delayed_disconnect_cleanup` into a testable function**

In `backend/ws/router.py`, the closure currently lives inside the `finally` block of the WS handler and runs after `asyncio.sleep(10)`. Extract its body into a module-level helper so we can call it directly from tests, and remove the `cancel_all_for_user` call. Replace lines 281-318 (the `_delayed_disconnect_cleanup` definition and its surrounding `asyncio.create_task` invocation) with:

```python
        # Spawn the disconnect cleanup as a fire-and-forget background
        # task — it sleeps for the grace period and then runs cleanup
        # if the user has not reconnected.
        asyncio.create_task(
            _delayed_disconnect_cleanup(
                user_id=user_id,
                connection_id=connection_id,
            )
        )
```

…and add the module-level helper near the top of `router.py`, just below the imports:

```python
async def _delayed_disconnect_cleanup(
    *,
    user_id: str,
    connection_id: str,
) -> None:
    """Run cleanup actions a few seconds after a WS disconnect.

    The 10-second grace absorbs flaky-network reconnects. After the
    grace, if the user is still offline:
    - Pending client-side tool futures are resolved with a synthetic
      'client disconnected' error so the inference loop can complete
      cleanly without the user.
    - The MCP registry tied to this WS connection is removed.

    What this function NO LONGER does (compared to the pre-background-
    completions design):
    - It does **not** cancel inflight inferences. They run to natural
      completion and persist their answers, even if the user never
      reconnects. See devdocs/specs/2026-05-07-background-completions-
      design.md.
    - It does **not** trigger disconnect-extraction directly. That is
      now anchored to inference cleanup (Task 4) so the extractor sees
      the final answers, not snapshots taken mid-stream.
    """
    try:
        await asyncio.sleep(10)
        await _disconnect_cleanup_for_test(
            user_id=user_id,
            connection_id=connection_id,
            has_reconnect=manager_has_reconnect(user_id),
        )
    except Exception as exc:
        _log.error(
            "Error in delayed disconnect cleanup for user %s: %s",
            user_id, exc,
        )


def manager_has_reconnect(user_id: str) -> bool:
    """Has the user reconnected during the grace period?"""
    from backend.ws.manager import get_manager
    return get_manager().has_connections(user_id)


async def _disconnect_cleanup_for_test(
    *,
    user_id: str,
    connection_id: str,
    has_reconnect: bool,
) -> None:
    """Body of the disconnect cleanup, exposed for tests.

    Performs the post-grace cleanup that does not depend on sleeping.
    """
    if has_reconnect:
        return
    try:
        get_client_dispatcher().cancel_for_user(user_id)
    except Exception:
        _log.warning(
            "Failed to resolve pending client tools for user %s",
            user_id, exc_info=True,
        )
    remove_mcp_registry(connection_id)
```

(Where `_log` is the existing module logger. Confirm the import for `get_client_dispatcher` and `remove_mcp_registry` is already at the top of `router.py` — Task 0 grep shows it is.)

Note what is **deliberately removed** from the old code:

- `cancel_all_for_user(user_id)` call — gone.
- `trigger_disconnect_extraction(user_id)` call — gone (moved to Task 4).

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONPATH=. uv run pytest backend/tests/ws/test_disconnect_cleanup.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full WS test suite to check for regressions**

```bash
PYTHONPATH=. uv run pytest backend/tests/ws/ -v
```

Expected: all pass (some tests for the old grace-cancel behaviour will need to be deleted or rewritten — see Step 6).

- [ ] **Step 6: Update or remove tests for the old "grace then cancel" behaviour**

If any pre-existing test in `backend/tests/ws/` asserts that an inference is cancelled after WS disconnect, it must now be flipped to the opposite assertion (the inference survives). Search:

```bash
rg -nl "cancel_all_for_user|disconnect.*cancel|grace" backend/tests/ws/
```

For each matching test, read it and decide:
- If it asserts the old cancel-on-disconnect behaviour → flip the assertion (or replace with a "stays alive" test).
- If it tests the client-tool resolve or MCP cleanup → keep unchanged.

Re-run the test suite after edits.

- [ ] **Step 7: Commit**

```bash
git add backend/ws/router.py backend/tests/ws/test_disconnect_cleanup.py
git commit -m "Stop cancelling inferences on WS disconnect"
```

---

## Task 4: Backend — Disconnect-Extraction Anchored to Inference Cleanup

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py` (run_inference finally block, plus a per-user lock helper)
- Modify: `backend/ws/router.py` (add the 30 s safety-net trigger)
- Test: `backend/tests/modules/chat/test_disconnect_extraction_anchor.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/modules/chat/test_disconnect_extraction_anchor.py`:

```python
"""Disconnect-extraction trigger fires when (no connections) AND (no inflight)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.chat._orchestrator import (
    _cancel_events,
    _inflight,
    maybe_trigger_disconnect_extraction,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    _cancel_events.clear()
    _inflight.clear()
    yield
    _cancel_events.clear()
    _inflight.clear()


@pytest.mark.asyncio
async def test_trigger_fires_when_user_offline_and_no_inflight():
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=False,
    ):
        await maybe_trigger_disconnect_extraction("user-a")
        mock_trigger.assert_awaited_once_with("user-a")


@pytest.mark.asyncio
async def test_trigger_does_not_fire_while_inflight_remains():
    _inflight["cor-1"] = ("user-a", "session-x")
    _cancel_events["cor-1"] = asyncio.Event()
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=False,
    ):
        await maybe_trigger_disconnect_extraction("user-a")
        mock_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_trigger_does_not_fire_while_user_still_connected():
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=True,
    ):
        await maybe_trigger_disconnect_extraction("user-a")
        mock_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_invocations_trigger_only_once():
    """Two inferences finish at the same instant → only one extraction."""
    with patch(
        "backend.modules.chat._orchestrator.trigger_disconnect_extraction",
        new=AsyncMock(),
    ) as mock_trigger, patch(
        "backend.modules.chat._orchestrator._has_connections",
        return_value=False,
    ):
        await asyncio.gather(
            maybe_trigger_disconnect_extraction("user-a"),
            maybe_trigger_disconnect_extraction("user-a"),
            maybe_trigger_disconnect_extraction("user-a"),
        )
        # Lock serialises them; the first wins, the others see "already
        # triggered for this offline window" and skip.
        assert mock_trigger.await_count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/chat/test_disconnect_extraction_anchor.py -v
```

Expected: FAIL with `cannot import name 'maybe_trigger_disconnect_extraction'`.

- [ ] **Step 3: Implement the anchor function and the per-user lock**

In `backend/modules/chat/_orchestrator.py`, add near the top of the module (after the existing in-flight registries):

```python
# Per-user lock that serialises the disconnect-extraction trigger check.
# Without this, two inferences finishing simultaneously could both observe
# "no connections and no inflight" and both call trigger_disconnect_extraction.
_disconnect_extraction_locks: dict[str, asyncio.Lock] = {}

# One-shot guard so a single offline window only triggers extraction once,
# even if the user has multiple inferences finish back-to-back. Cleared
# when the user reconnects (see WS connect path).
_disconnect_extraction_done: set[str] = set()


def _get_disconnect_extraction_lock(user_id: str) -> asyncio.Lock:
    lock = _disconnect_extraction_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _disconnect_extraction_locks[user_id] = lock
    return lock


def _has_connections(user_id: str) -> bool:
    """Indirection so tests can patch the connection check without
    standing up the full WS manager."""
    from backend.ws.manager import get_manager
    return get_manager().has_connections(user_id)


def reset_disconnect_extraction_guard(user_id: str) -> None:
    """Called from the WS connect path: a fresh connection means the
    next offline window should be eligible for extraction again."""
    _disconnect_extraction_done.discard(user_id)
```

Then add the anchor itself, ideally near the existing `cancel_inflight_for_session`:

```python
async def maybe_trigger_disconnect_extraction(user_id: str) -> None:
    """If the user has no connections and no inflight inferences,
    trigger memory extraction for them. Idempotent within an offline
    window via _disconnect_extraction_done."""
    lock = _get_disconnect_extraction_lock(user_id)
    async with lock:
        if user_id in _disconnect_extraction_done:
            return
        if _has_connections(user_id):
            return
        if _user_has_inflight(user_id):
            return
        try:
            await trigger_disconnect_extraction(user_id)
            _disconnect_extraction_done.add(user_id)
        except Exception:
            _log.error(
                "disconnect_extraction_failed user=%s", user_id, exc_info=True,
            )
```

`trigger_disconnect_extraction` already lives in this same module (`_orchestrator.py:1087`); a direct call is fine. The test patches it via `backend.modules.chat._orchestrator.trigger_disconnect_extraction`, which hits the same symbol.

- [ ] **Step 4: Wire the anchor into `run_inference`'s finally block**

In `run_inference`, locate the `finally` block where `_inflight.pop(correlation_id, None)` happens. After the pop, append:

```python
        try:
            await maybe_trigger_disconnect_extraction(user_id)
        except Exception:
            _log.warning(
                "maybe_trigger_disconnect_extraction raised in run_inference finally for user=%s",
                user_id, exc_info=True,
            )
```

Same in `handle_incognito_send`'s finally block (search for the `_inflight.pop`).

- [ ] **Step 5: Reset the guard on WS connect**

In `backend/ws/router.py`, in the WS handshake path (the start of the WS handler, after auth resolves the user), add a single call:

```python
from backend.modules.chat import reset_disconnect_extraction_guard
reset_disconnect_extraction_guard(user_id)
```

Re-export `reset_disconnect_extraction_guard` from `backend/modules/chat/__init__.py` next to the other exports.

- [ ] **Step 6: Add the 30 s safety-net trigger to the disconnect cleanup**

The safety net handles "user disconnects with zero inflight inferences" (otherwise the inference-cleanup anchor never fires for them). In `backend/ws/router.py`, extend `_disconnect_cleanup_for_test` (created in Task 3):

```python
async def _disconnect_cleanup_for_test(
    *,
    user_id: str,
    connection_id: str,
    has_reconnect: bool,
) -> None:
    if has_reconnect:
        return
    try:
        get_client_dispatcher().cancel_for_user(user_id)
    except Exception:
        _log.warning(
            "Failed to resolve pending client tools for user %s",
            user_id, exc_info=True,
        )
    remove_mcp_registry(connection_id)

    # Safety net: if the user disconnected and has no inflight inferences
    # right now (so the inference-cleanup anchor will never fire), trigger
    # extraction directly. Wait an additional 30 s after the 10 s grace so
    # any inference that started just before disconnect has a chance to
    # register itself in _inflight.
    asyncio.create_task(_extraction_safety_net(user_id))


async def _extraction_safety_net(user_id: str) -> None:
    try:
        await asyncio.sleep(30)
        from backend.modules.chat import maybe_trigger_disconnect_extraction
        await maybe_trigger_disconnect_extraction(user_id)
    except Exception:
        _log.warning(
            "extraction safety net failed for user %s",
            user_id, exc_info=True,
        )
```

- [ ] **Step 7: Run all new tests**

```bash
PYTHONPATH=. uv run pytest backend/tests/modules/chat/test_disconnect_extraction_anchor.py backend/tests/modules/chat/test_orchestrator_cancel.py backend/tests/ws/test_disconnect_cleanup.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/chat/__init__.py backend/ws/router.py backend/tests/modules/chat/test_disconnect_extraction_anchor.py
git commit -m "Anchor disconnect-extraction to inference cleanup"
```

---

## Task 5: Frontend — Session-Scoped Streaming State

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts` (whole file — refactor to per-session state)
- Modify: `frontend/src/features/chat/children/chatStoreSink.ts` (pass session id through)
- Test: `frontend/src/core/store/chatStore.test.ts` (extend existing)

- [ ] **Step 1: Sketch the target shape**

Conceptually we are moving the eight streaming-state fields out of the top-level state and into a per-session record. A new map holds them:

```typescript
interface SessionStreamingState {
  isWaitingForResponse: boolean
  isStreaming: boolean
  correlationId: string | null
  streamingContent: string
  streamingThinking: string
  streamingEvents: TimelineEntry[]
  streamingRefusalText: string | null
  activeToolCalls: ActiveToolCall[]
  visionDescriptions: Record<string, LiveVisionDescription>
  streamingSlow: boolean
}
```

The existing top-level fields `messages`, `messagePillContents`, `contextStatus`, `contextFillPercentage`, `contextUsedTokens`, `contextMaxTokens`, `error`, `sessionTitle`, `toolsEnabled`, `autoRead`, `reasoningOverride`, `activeProjectId`, `activeSessionId` stay top-level for now — they are not "streaming state per session", they are session-load state that swaps when the user switches.

Streaming state moves into `streamsBySession: Map<string, SessionStreamingState>`. Existing read accessors on the store become "look up by activeSessionId, return zeros if absent".

- [ ] **Step 2: Write the failing tests for the new shape**

Append to `frontend/src/core/store/chatStore.test.ts` (or create `frontend/src/core/store/chatStore.background.test.ts` to keep diffs scoped):

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from './chatStore'

describe('chatStore — session-scoped streaming state', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  it('startStreaming(sessionId) writes into streamsBySession', () => {
    const { startStreaming, getStreamFor } = useChatStore.getState()
    startStreaming('cor-1', { sessionId: 'session-A' })
    const stream = getStreamFor('session-A')
    expect(stream).not.toBeNull()
    expect(stream?.isStreaming).toBe(true)
    expect(stream?.correlationId).toBe('cor-1')
  })

  it('two sessions stream independently', () => {
    const { startStreaming, appendStreamingContent, getStreamFor } =
      useChatStore.getState()

    startStreaming('cor-A', { sessionId: 'session-A' })
    startStreaming('cor-B', { sessionId: 'session-B' })

    appendStreamingContent('hello A', { sessionId: 'session-A' })
    appendStreamingContent('hello B', { sessionId: 'session-B' })

    expect(getStreamFor('session-A')?.streamingContent).toBe('hello A')
    expect(getStreamFor('session-B')?.streamingContent).toBe('hello B')
  })

  it('reset(sessionId) does NOT discard streaming state for OTHER sessions', () => {
    const { startStreaming, reset, getStreamFor } = useChatStore.getState()
    startStreaming('cor-A', { sessionId: 'session-A' })
    startStreaming('cor-B', { sessionId: 'session-B' })

    reset('session-A')

    expect(getStreamFor('session-A')).toBeNull()
    expect(getStreamFor('session-B')?.isStreaming).toBe(true)
  })

  it('finishStreaming clears the slot for that session', () => {
    const { startStreaming, finishStreaming, getStreamFor } =
      useChatStore.getState()
    startStreaming('cor-A', { sessionId: 'session-A' })
    finishStreaming(
      { id: 'm1', role: 'assistant', content: 'done', token_count: 1 } as any,
      'green',
      0,
      0,
      0,
      undefined,
      { sessionId: 'session-A' },
    )
    expect(getStreamFor('session-A')).toBeNull()
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/core/store/chatStore.background.test.ts
```

Expected: FAIL with `getStreamFor is not a function` (or similar).

- [ ] **Step 4: Refactor the store**

Replace the contents of `frontend/src/core/store/chatStore.ts` with the new shape. The diff is large; here is the target structure (paste in place of the existing file, preserving the existing imports, types, and non-streaming actions verbatim):

```typescript
import { create } from 'zustand'
import type { ChatMessageDto, TimelineEntry } from '../api/chat'

type ContextStatus = 'green' | 'yellow' | 'orange' | 'red'

interface ChatError {
  errorCode: string
  recoverable: boolean
  userMessage: string
}

interface ActiveToolCall {
  id: string
  toolName: string
  arguments: Record<string, unknown>
  status: 'running' | 'done'
}

export interface LiveVisionDescription {
  file_id: string
  display_name: string
  model_id: string
  status: 'pending' | 'success' | 'error'
  text: string | null
  error: string | null
}

export interface SessionStreamingState {
  isWaitingForResponse: boolean
  isStreaming: boolean
  correlationId: string | null
  streamingContent: string
  streamingThinking: string
  streamingEvents: TimelineEntry[]
  streamingRefusalText: string | null
  activeToolCalls: ActiveToolCall[]
  visionDescriptions: Record<string, LiveVisionDescription>
  streamingSlow: boolean
}

const EMPTY_STREAM: SessionStreamingState = {
  isWaitingForResponse: false,
  isStreaming: false,
  correlationId: null,
  streamingContent: '',
  streamingThinking: '',
  streamingEvents: [],
  streamingRefusalText: null,
  activeToolCalls: [],
  visionDescriptions: {},
  streamingSlow: false,
}

interface ChatState {
  // Per-session streaming slots — survive across activeSessionId changes.
  streamsBySession: Map<string, SessionStreamingState>

  // Session-load state (these still swap on session switch).
  messages: ChatMessageDto[]
  messagePillContents: Record<string, Map<string, string>>
  contextStatus: ContextStatus
  contextFillPercentage: number
  contextUsedTokens: number
  contextMaxTokens: number
  error: ChatError | null
  sessionTitle: string | null
  toolsEnabled: boolean
  autoRead: boolean
  reasoningOverride: boolean | null
  activeProjectId: string | null
  activeSessionId: string | null

  // Read accessors
  getStreamFor: (sessionId: string) => SessionStreamingState | null

  // Streaming actions — every action takes an explicit { sessionId }
  // since callers may write into a stream that is not the active one.
  setMessages: (messages: ChatMessageDto[]) => void
  appendMessage: (message: ChatMessageDto) => void
  setWaitingForResponse: (waiting: boolean, opts: { sessionId: string }) => void
  startStreaming: (correlationId: string, opts: { sessionId: string }) => void
  appendStreamingContent: (delta: string, opts: { sessionId: string }) => void
  replaceInStreamingContent: (
    search: string, replacement: string, opts: { sessionId: string },
  ) => void
  appendStreamingThinking: (delta: string, opts: { sessionId: string }) => void
  appendStreamingEvent: (entry: TimelineEntry, opts: { sessionId: string }) => void
  setStreamingRefusalText: (text: string | null, opts: { sessionId: string }) => void
  addToolCall: (tc: ActiveToolCall, opts: { sessionId: string }) => void
  completeToolCall: (toolCallId: string, opts: { sessionId: string }) => void
  upsertVisionDescription: (
    correlationId: string,
    payload: LiveVisionDescription,
    opts: { sessionId: string },
  ) => void
  finishStreaming: (
    finalMessage: ChatMessageDto,
    contextStatus: ContextStatus,
    fillPercentage: number,
    usedTokens: number,
    maxTokens: number,
    pillContents: Map<string, string> | undefined,
    opts: { sessionId: string },
  ) => void
  cancelStreaming: (opts: { sessionId: string }) => void
  setStreamingSlow: (slow: boolean, opts: { sessionId: string }) => void

  // Non-streaming actions — unchanged
  truncateAfter: (messageId: string) => void
  updateMessage: (messageId: string, content: string, tokenCount: number) => void
  swapMessageId: (clientId: string, realId: string, patch?: Partial<ChatMessageDto>) => void
  deleteMessage: (messageId: string) => void
  setError: (error: ChatError) => void
  clearError: () => void
  setSessionTitle: (title: string | null) => void
  setToolsEnabled: (value: boolean) => void
  setAutoRead: (value: boolean) => void
  setContextStatus: (status: ContextStatus) => void
  setContextFillPercentage: (percentage: number) => void
  setContextTokens: (used: number, max: number) => void
  setReasoningOverride: (override: boolean | null) => void
  setActiveProjectId: (projectId: string | null) => void
  reset: (sessionId?: string) => void
}

const INITIAL_NON_STREAMING = {
  messages: [] as ChatMessageDto[],
  messagePillContents: {} as Record<string, Map<string, string>>,
  contextStatus: 'green' as ContextStatus,
  contextFillPercentage: 0,
  contextUsedTokens: 0,
  contextMaxTokens: 0,
  error: null as ChatError | null,
  sessionTitle: null as string | null,
  toolsEnabled: false,
  autoRead: false,
  reasoningOverride: null as boolean | null,
  activeProjectId: null as string | null,
  activeSessionId: null as string | null,
}

function withStream(
  m: Map<string, SessionStreamingState>,
  sessionId: string,
  patch: Partial<SessionStreamingState>,
): Map<string, SessionStreamingState> {
  const next = new Map(m)
  const prev = next.get(sessionId) ?? EMPTY_STREAM
  next.set(sessionId, { ...prev, ...patch })
  return next
}

function clearStream(
  m: Map<string, SessionStreamingState>,
  sessionId: string,
): Map<string, SessionStreamingState> {
  if (!m.has(sessionId)) return m
  const next = new Map(m)
  next.delete(sessionId)
  return next
}

export const useChatStore = create<ChatState>((set, get) => ({
  streamsBySession: new Map(),
  ...INITIAL_NON_STREAMING,

  getStreamFor: (sessionId) => get().streamsBySession.get(sessionId) ?? null,

  setMessages: (messages) => set({ messages }),
  appendMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),

  setWaitingForResponse: (waiting, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        isWaitingForResponse: waiting,
      }),
    })),

  startStreaming: (correlationId, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        ...EMPTY_STREAM,
        isStreaming: true,
        correlationId,
      }),
    })),

  appendStreamingContent: (delta, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingContent: prev.streamingContent + delta,
          streamingSlow: false,
        }),
      }
    }),

  replaceInStreamingContent: (search, replacement, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingContent: prev.streamingContent.replace(search, replacement),
        }),
      }
    }),

  appendStreamingThinking: (delta, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingThinking: prev.streamingThinking + delta,
          streamingSlow: false,
        }),
      }
    }),

  appendStreamingEvent: (entry, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      const seq = prev.streamingEvents.length
      const next = { ...entry, seq } as TimelineEntry
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          streamingEvents: [...prev.streamingEvents, next],
        }),
      }
    }),

  setStreamingRefusalText: (text, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingRefusalText: text,
      }),
    })),

  addToolCall: (tc, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      const idx = prev.activeToolCalls.findIndex((x) => x.id === tc.id)
      const nextCalls = idx >= 0
        ? prev.activeToolCalls.map((x, i) => (i === idx ? tc : x))
        : [...prev.activeToolCalls, tc]
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          activeToolCalls: nextCalls,
        }),
      }
    }),

  completeToolCall: (toolCallId, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          activeToolCalls: prev.activeToolCalls.map((tc) =>
            tc.id === toolCallId ? { ...tc, status: 'done' as const } : tc,
          ),
        }),
      }
    }),

  upsertVisionDescription: (correlationId, payload, { sessionId }) =>
    set((s) => {
      const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
      return {
        streamsBySession: withStream(s.streamsBySession, sessionId, {
          visionDescriptions: {
            ...prev.visionDescriptions,
            [`${correlationId}:${payload.file_id}`]: payload,
          },
        }),
      }
    }),

  finishStreaming: (
    finalMessage,
    contextStatus,
    fillPercentage,
    usedTokens = 0,
    maxTokens = 0,
    pillContents,
    { sessionId },
  ) =>
    set((s) => {
      const nextPillCache =
        pillContents && pillContents.size > 0 && finalMessage.id
          ? { ...s.messagePillContents, [finalMessage.id]: pillContents }
          : s.messagePillContents
      // Only append the message into the visible transcript when the
      // finishing stream belongs to the active session. Background-completion
      // results are loaded from the DB on next session switch.
      const messages =
        sessionId === s.activeSessionId
          ? [...s.messages, finalMessage]
          : s.messages
      return {
        streamsBySession: clearStream(s.streamsBySession, sessionId),
        messages,
        contextStatus: sessionId === s.activeSessionId ? contextStatus : s.contextStatus,
        contextFillPercentage: sessionId === s.activeSessionId ? fillPercentage : s.contextFillPercentage,
        contextUsedTokens: sessionId === s.activeSessionId ? usedTokens : s.contextUsedTokens,
        contextMaxTokens: sessionId === s.activeSessionId ? maxTokens : s.contextMaxTokens,
        messagePillContents: nextPillCache,
      }
    }),

  cancelStreaming: ({ sessionId }) =>
    set((s) => ({ streamsBySession: clearStream(s.streamsBySession, sessionId) })),

  setStreamingSlow: (slow, { sessionId }) =>
    set((s) => ({
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingSlow: slow,
      }),
    })),

  truncateAfter: (messageId) =>
    set((s) => {
      const idx = s.messages.findIndex((m) => m.id === messageId)
      if (idx === -1) return s
      const nextMessages = s.messages.slice(0, idx + 1)
      const surviving = new Set(nextMessages.map((m) => m.id))
      const nextCache: Record<string, Map<string, string>> = {}
      for (const [k, v] of Object.entries(s.messagePillContents)) {
        if (surviving.has(k)) nextCache[k] = v
      }
      return { messages: nextMessages, messagePillContents: nextCache }
    }),

  updateMessage: (messageId, content, tokenCount) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, content, token_count: tokenCount } : m,
      ),
    })),

  swapMessageId: (clientId, realId, patch) =>
    set((s) => {
      const messages = s.messages.map((m) =>
        m.id === clientId ? { ...m, id: realId, ...(patch ?? {}) } : m,
      )
      let messagePillContents = s.messagePillContents
      if (clientId in messagePillContents) {
        const { [clientId]: cached, ...rest } = messagePillContents
        messagePillContents = { ...rest, [realId]: cached }
      }
      return { messages, messagePillContents }
    }),

  deleteMessage: (messageId) =>
    set((s) => {
      const { [messageId]: _removed, ...nextCache } = s.messagePillContents
      return {
        messages: s.messages.filter((m) => m.id !== messageId),
        messagePillContents: nextCache,
      }
    }),

  setError: (error) => set({ error }),
  clearError: () => set({ error: null }),
  setSessionTitle: (title) => set({ sessionTitle: title }),
  setToolsEnabled: (value) => set({ toolsEnabled: value }),
  setAutoRead: (value) => set({ autoRead: value }),
  setContextStatus: (status) => set({ contextStatus: status }),
  setContextFillPercentage: (percentage) => set({ contextFillPercentage: percentage }),
  setContextTokens: (used, max) => set({ contextUsedTokens: used, contextMaxTokens: max }),
  setReasoningOverride: (override) => set({ reasoningOverride: override }),
  setActiveProjectId: (projectId) => set({ activeProjectId: projectId }),

  // reset(sessionId) — clear non-streaming state and update activeSessionId,
  // but DO NOT clear streamsBySession. Other sessions may have inflight
  // background completions whose state must survive the switch.
  reset: (sessionId) =>
    set((s) => {
      // If a sessionId is provided AND it has a streaming slot, that slot
      // belongs to the session being switched TO — keep it. If no sessionId,
      // wipe the slot for the previously-active session (it was a true reset).
      let nextStreams = s.streamsBySession
      if (sessionId === undefined && s.activeSessionId) {
        nextStreams = clearStream(nextStreams, s.activeSessionId)
      }
      return {
        ...INITIAL_NON_STREAMING,
        streamsBySession: nextStreams,
        activeSessionId: sessionId ?? null,
      }
    }),
}))
```

- [ ] **Step 5: Run the new tests**

```bash
cd frontend && pnpm vitest run src/core/store/chatStore.background.test.ts
```

Expected: all four pass.

- [ ] **Step 6: Run the existing chatStore tests, expect failures, update them**

```bash
cd frontend && pnpm vitest run src/core/store/chatStore.test.ts src/features/chat/__tests__/chatStore.test.ts
```

Existing tests in those two files call `startStreaming(corId)` without the `{ sessionId }` argument and read the old top-level fields. Update each test:

- Add `{ sessionId: 'session-test' }` to every streaming-action call.
- Replace reads of `useChatStore.getState().isStreaming` etc. with `useChatStore.getState().getStreamFor('session-test')?.isStreaming`.
- Add `useChatStore.getState().reset('session-test')` to test setup so `activeSessionId` matches the test's session id (otherwise `finishStreaming` won't append messages — see the implementation).

Re-run after each batch of fixes until both files pass.

- [ ] **Step 7: Update every caller of the old streaming API in production code**

```bash
rg -n "startStreaming\(|appendStreamingContent\(|finishStreaming\(|cancelStreaming\(|setWaitingForResponse\(|setStreamingSlow\(|appendStreamingThinking\(|appendStreamingEvent\(|setStreamingRefusalText\(|addToolCall\(|completeToolCall\(|upsertVisionDescription\(|replaceInStreamingContent\(" frontend/src/ \
  --type ts --type tsx | grep -v __tests__ | grep -v ".test." | grep -v ".spec."
```

For each match, decide the session id source:
- If the call is inside a `responseTaskGroup` child (e.g. `chatStoreSink.ts`): the Group has a `sessionId` field — pass it through.
- If the call is in a hook reading the store directly (e.g. `useChatStream.ts`): use the active session id from the chatStore (or the correlation's session id when known).

The `chatStoreSink` child gets a single small refactor. Find its current `cancelStreaming()` usage (line 47 area):

```typescript
import { useChatStore } from '@/core/store/chatStore'
// ...inside the child factory, where 'sessionId' is in scope from the Group...
useChatStore.getState().cancelStreaming({ sessionId })
```

Apply the same to every action it invokes.

- [ ] **Step 8: Run full frontend build**

```bash
cd frontend && pnpm run build
```

Expected: clean build, zero errors.

- [ ] **Step 9: Run the full frontend test suite**

```bash
cd frontend && pnpm vitest run
```

Expected: all pass. Address each failure by following the same pattern (add `{ sessionId }` param, read via `getStreamFor`).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/store/chatStore.test.ts \
  frontend/src/core/store/chatStore.background.test.ts frontend/src/features/chat/
git commit -m "Make chatStore streaming state session-scoped"
```

---

## Task 6: Frontend — Multi-Group Registry in responseTaskGroup

**Files:**
- Modify: `frontend/src/features/chat/responseTaskGroup.ts:235-298` (registry section)
- Modify: `frontend/src/features/chat/ChatView.tsx:471, 1025, 1030, 1047` (call sites)
- Modify: `frontend/src/features/voice/bargeController.ts:111-163` (call sites)
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts:560-565` (call sites)
- Test: `frontend/src/features/chat/__tests__/responseTaskGroup.registry.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/chat/__tests__/responseTaskGroup.registry.test.ts`:

```typescript
import { describe, it, expect, vi } from 'vitest'
import {
  createResponseTaskGroup,
  registerActiveGroup,
  getActiveGroupForSession,
  cancelGroupForSession,
  clearGroupForSession,
} from '../responseTaskGroup'

const noopLogger = {
  info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn(),
}

function makeGroup(sessionId: string, correlationId: string) {
  return createResponseTaskGroup({
    correlationId,
    sessionId,
    userId: 'user-test',
    children: [],
    sendWsMessage: vi.fn(),
    logger: noopLogger,
  })
}

describe('responseTaskGroup multi-group registry', () => {
  it('registers groups under their session id and looks them up by session', () => {
    const a = makeGroup('session-A', 'cor-A')
    const b = makeGroup('session-B', 'cor-B')
    registerActiveGroup(a)
    registerActiveGroup(b)

    expect(getActiveGroupForSession('session-A')).toBe(a)
    expect(getActiveGroupForSession('session-B')).toBe(b)
    clearGroupForSession('session-A')
    clearGroupForSession('session-B')
  })

  it('registering a second group for the same session supersedes the first', () => {
    const a = makeGroup('session-A', 'cor-A1')
    const b = makeGroup('session-A', 'cor-A2')
    registerActiveGroup(a)
    registerActiveGroup(b)

    expect(getActiveGroupForSession('session-A')).toBe(b)
    expect(a.state).toBe('cancelled')
    clearGroupForSession('session-A')
  })

  it('cancelGroupForSession only affects the named session', () => {
    const a = makeGroup('session-A', 'cor-A')
    const b = makeGroup('session-B', 'cor-B')
    registerActiveGroup(a)
    registerActiveGroup(b)

    cancelGroupForSession('session-A', 'teardown')

    expect(a.state).toBe('cancelled')
    expect(b.state).toBe('before-first-delta')
    clearGroupForSession('session-B')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/responseTaskGroup.registry.test.ts
```

Expected: FAIL with `getActiveGroupForSession is not exported`.

- [ ] **Step 3: Refactor the registry**

In `frontend/src/features/chat/responseTaskGroup.ts`, replace lines 235-298 (everything after the closing brace of `createResponseTaskGroup`) with:

```typescript
// --- Registry --------------------------------------------------------------

const groupsBySession = new Map<string, ResponseTaskGroup>()

export type GroupListener = (
  sessionId: string,
  group: ResponseTaskGroup | null,
) => void

const listeners = new Set<GroupListener>()

export function subscribeGroups(fn: GroupListener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

function notifyAll(sessionId: string, group: ResponseTaskGroup | null, logger?: GroupLogger): void {
  const snapshot = Array.from(listeners)
  for (const fn of snapshot) {
    try {
      fn(sessionId, group)
    } catch (err) {
      if (logger) logger.error('[group registry] listener threw', err)
      else console.error('[group registry] listener threw', err)
    }
  }
}

export function registerActiveGroup(g: ResponseTaskGroup): void {
  const existing = groupsBySession.get(g.sessionId)
  if (existing && existing.state !== 'done' && existing.state !== 'cancelled' && existing !== g) {
    existing.cancel('superseded')
  }
  groupsBySession.set(g.sessionId, g)
  notifyAll(g.sessionId, g)
}

/** Replaces the old `cancelCurrentActiveGroup`. */
export function cancelGroupForSession(
  sessionId: string,
  reason: CancelReason = 'superseded',
): void {
  const g = groupsBySession.get(sessionId)
  if (g && g.state !== 'done' && g.state !== 'cancelled') {
    g.cancel(reason)
  }
}

export function getActiveGroupForSession(sessionId: string): ResponseTaskGroup | null {
  return groupsBySession.get(sessionId) ?? null
}

/** Iterate over every currently-active group across all sessions. */
export function forEachActiveGroup(fn: (g: ResponseTaskGroup) => void): void {
  for (const g of groupsBySession.values()) fn(g)
}

export function clearGroupForSession(sessionId: string): void {
  const g = groupsBySession.get(sessionId)
  if (g) {
    groupsBySession.delete(sessionId)
    notifyAll(sessionId, null)
  }
}
```

In the same file, update the `transition` helper inside `createResponseTaskGroup` so the "done"/"cancelled" branch calls `clearGroupForSession(g.sessionId)` instead of the old `clearActiveGroup(group)`:

```typescript
  function transition(next: GroupState, reason?: CancelReason): void {
    const reasonSuffix = reason ? ` (reason=${reason})` : ''
    logger.info(`${prefix} ${state} → ${next}${reasonSuffix}`)
    state = next
    notifyAll(sessionId, group, logger)
    if (state === 'done' || state === 'cancelled') {
      clearGroupForSession(sessionId)
    }
  }
```

Remove the old `subscribeActiveGroup`, `notifyActiveGroup`, `cancelCurrentActiveGroup`, `getActiveGroup`, `clearActiveGroup`, and the `activeGroup` module-level variable.

- [ ] **Step 4: Update every call site of the removed exports**

```bash
rg -n "cancelCurrentActiveGroup|getActiveGroup\(|subscribeActiveGroup|clearActiveGroup" frontend/src/
```

For each match outside `__tests__`:

- `getActiveGroup()` → `getActiveGroupForSession(sessionId)` — the caller must have a session id (use the active session id from chatStore if not already in scope).
- `cancelCurrentActiveGroup(reason)` → `cancelGroupForSession(sessionId, reason)`.
- `subscribeActiveGroup(fn)` → `subscribeGroups((sid, g) => { if (sid === activeSessionId) fn(g) })` — sidebar consumers care about all sessions, the active-only consumers filter by id.

Concretely:

`ChatView.tsx`:
- Line ~471: `cancelCurrentActiveGroup('teardown')` → `cancelGroupForSession(sessionIdAtMount, 'teardown')` where `sessionIdAtMount` is captured from props at component mount (so that StrictMode unmounts a still-mounted parent view do not accidentally cancel a freshly-mounted child).
- Lines 1025, 1030, 1047: `getActiveGroup()?.cancel('teardown')` → `getActiveGroupForSession(sessionId)?.cancel('teardown')` with `sessionId` from the surrounding hook scope.

`bargeController.ts:163`: `getActiveGroup()?.cancel('teardown')` → take the session id from the controller's bound session (the controller is created per ChatView so it knows its session). If not already in scope, thread it through the controller's constructor.

`useConversationMode.ts:560-565`: same pattern.

- [ ] **Step 5: Update tests that reference the old API**

```bash
rg -n "cancelCurrentActiveGroup|getActiveGroup\(|subscribeActiveGroup|clearActiveGroup" frontend/src/
```

After Step 4 the only remaining matches should be in `__tests__` directories. Update each test file with the same renames.

- [ ] **Step 6: Run the new test plus the full responseTaskGroup test set**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/responseTaskGroup
```

Expected: all pass.

- [ ] **Step 7: Run full build**

```bash
cd frontend && pnpm run build
```

Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/chat/responseTaskGroup.ts \
  frontend/src/features/chat/ChatView.tsx \
  frontend/src/features/voice/bargeController.ts \
  frontend/src/features/voice/hooks/useConversationMode.ts \
  frontend/src/features/chat/__tests__/responseTaskGroup.registry.test.ts \
  frontend/src/features/chat/__tests__/
git commit -m "Replace single active group with per-session group registry"
```

---

## Task 7: Frontend — chatStoreSink Survives Teardown; Voice Children Tear Down

**Files:**
- Modify: `frontend/src/features/chat/children/chatStoreSink.ts`
- Modify: `frontend/src/features/voice/children/*` (each voice child's `onCancel`/`teardown`)
- Test: `frontend/src/features/chat/children/__tests__/chatStoreSink.test.ts` (extend)

- [ ] **Step 1: Read `chatStoreSink.ts` to understand current teardown behaviour**

Open the file. Key methods: `onCancel(reason, token)` and `teardown()`. Today, `onCancel('teardown')` calls `cancelStreaming()`, wiping the slot. We need the opposite: on `teardown` reason, leave the slot intact (so the partial stream is still visible when the user returns) but stop binding to the now-unmounted UI.

- [ ] **Step 2: Write the failing test**

Append to `frontend/src/features/chat/children/__tests__/chatStoreSink.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { useChatStore } from '@/core/store/chatStore'
import { createChatStoreSink } from '../chatStoreSink'

describe('chatStoreSink teardown semantics', () => {
  it('teardown reason leaves the streaming slot intact for resume', () => {
    useChatStore.getState().reset('session-A')
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'session-A' })
    useChatStore.getState().appendStreamingContent('hello', { sessionId: 'session-A' })

    const sink = createChatStoreSink({ sessionId: 'session-A' })
    sink.onCancel('teardown', 'cor-1')

    expect(useChatStore.getState().getStreamFor('session-A')?.streamingContent).toBe('hello')
    expect(useChatStore.getState().getStreamFor('session-A')?.isStreaming).toBe(true)
  })

  it('user-stop reason clears the streaming slot', () => {
    useChatStore.getState().reset('session-A')
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'session-A' })
    useChatStore.getState().appendStreamingContent('hello', { sessionId: 'session-A' })

    const sink = createChatStoreSink({ sessionId: 'session-A' })
    sink.onCancel('user-stop', 'cor-1')

    expect(useChatStore.getState().getStreamFor('session-A')).toBeNull()
  })
})
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/chat/children/__tests__/chatStoreSink.test.ts
```

Expected: the first test fails (`'hello'` is gone after teardown).

- [ ] **Step 4: Update `chatStoreSink.onCancel` to branch on reason**

In `frontend/src/features/chat/children/chatStoreSink.ts`, locate the `onCancel` method. Replace its body with:

```typescript
    onCancel(reason: CancelReason, _token: string): void {
      // Background-completion semantics: 'teardown' = the UI is unmounting
      // (persona switch, history view, etc.) but the inference is still
      // running on the backend. Leave the streaming slot in place so a
      // future remount of the same session resumes the live stream.
      // Every other reason is a definitive end (user pressed Stop, a new
      // send superseded this one, etc.) — wipe the slot.
      if (reason === 'teardown') return
      useChatStore.getState().cancelStreaming({ sessionId })
    },
```

(`sessionId` is captured from the factory's `opts.sessionId`. If the existing factory doesn't take it, add it: `createChatStoreSink({ sessionId }: { sessionId: string })`.)

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd frontend && pnpm vitest run src/features/chat/children/__tests__/chatStoreSink.test.ts
```

Expected: PASS.

- [ ] **Step 6: Verify voice children still tear down on teardown**

Locate the voice children:

```bash
rg -n "onCancel" frontend/src/features/voice/children/
```

For each voice child (sentencer, audioPlayback, audioParser, …), confirm that `onCancel('teardown', …)` performs the same cleanup as `onCancel('user-stop', …)` — they all stop audio and reset their internal state. If any voice child has a teardown branch that leaves audio dangling, fix it: voice must die on teardown so audio does not bleed into a different persona.

If a voice child differentiates `'teardown'` to "don't clear", change it to clear unconditionally. Add or extend the relevant test.

- [ ] **Step 7: Run the full chat-children and voice test set**

```bash
cd frontend && pnpm vitest run src/features/chat/children src/features/voice
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/chat/children/chatStoreSink.ts \
  frontend/src/features/chat/children/__tests__/chatStoreSink.test.ts \
  frontend/src/features/voice/children/
git commit -m "Keep partial stream visible across teardown; voice still detaches"
```

---

## Task 8: UI — Sidebar Pulse-Dot and Stop Menu

**Files:**
- Create: `frontend/src/features/chat/StreamingIndicatorDot.tsx`
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx` (add the dot to session rows)
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx` (add right-click "Stop generation" menu entry)
- Modify: persona switcher component (likely `frontend/src/app/components/sidebar/PersonaSwitcher.tsx` or similar — locate via Step 1)
- Test: `frontend/src/features/chat/__tests__/StreamingIndicatorDot.test.tsx` (new)

- [ ] **Step 1: Locate the persona-switcher component**

```bash
rg -n "PersonaSwitcher|switchPersona" frontend/src/app/ | head
```

Note the file path; pulse-dot will be added there too.

- [ ] **Step 2: Build `StreamingIndicatorDot`**

Create `frontend/src/features/chat/StreamingIndicatorDot.tsx`:

```typescript
import { useChatStore } from '@/core/store/chatStore'
import { useShallow } from 'zustand/react/shallow'

interface Props {
  sessionId: string
  className?: string
}

/**
 * Subtle 6-px pulse-dot rendered next to a session row when that session
 * has an active inference streaming. Driven by chatStore.streamsBySession.
 *
 * Aesthetic: monochrome accent, gentle pulse — same restraint as inline
 * voice-tag pills. Not a status indicator with rich state; just "alive".
 */
export function StreamingIndicatorDot({ sessionId, className = '' }: Props) {
  const isStreaming = useChatStore(
    useShallow((s) => Boolean(s.streamsBySession.get(sessionId)?.isStreaming)),
  )
  if (!isStreaming) return null
  return (
    <span
      aria-label="response streaming"
      className={
        'inline-block h-1.5 w-1.5 rounded-full bg-white/70 ' +
        'animate-pulse-soft ' +
        className
      }
    />
  )
}
```

(`animate-pulse-soft` is a Tailwind utility we will define in Step 3 if it does not already exist. If the project already has a softer pulse keyframe in `tailwind.config.cjs`, reuse it.)

- [ ] **Step 3: Add `animate-pulse-soft` if missing**

Check Tailwind config:

```bash
rg -n "pulse-soft|pulse" frontend/tailwind.config.cjs frontend/tailwind.config.ts 2>/dev/null
```

If absent, add to the config's `theme.extend.keyframes` and `theme.extend.animation`:

```js
keyframes: {
  'pulse-soft': {
    '0%, 100%': { opacity: '0.4' },
    '50%': { opacity: '0.95' },
  },
},
animation: {
  'pulse-soft': 'pulse-soft 1.6s ease-in-out infinite',
},
```

- [ ] **Step 4: Write the indicator test**

Create `frontend/src/features/chat/__tests__/StreamingIndicatorDot.test.tsx`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useChatStore } from '@/core/store/chatStore'
import { StreamingIndicatorDot } from '../StreamingIndicatorDot'

describe('StreamingIndicatorDot', () => {
  beforeEach(() => {
    useChatStore.setState({ streamsBySession: new Map() })
  })

  it('renders nothing when no stream exists for the session', () => {
    const { container } = render(<StreamingIndicatorDot sessionId="x" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the dot when a stream is active for the session', () => {
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'x' })
    render(<StreamingIndicatorDot sessionId="x" />)
    expect(screen.getByLabelText('response streaming')).toBeInTheDocument()
  })

  it('does not render for a different session id', () => {
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'x' })
    const { container } = render(<StreamingIndicatorDot sessionId="y" />)
    expect(container.firstChild).toBeNull()
  })
})
```

- [ ] **Step 5: Run the test**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/StreamingIndicatorDot.test.tsx
```

Expected: all pass.

- [ ] **Step 6: Place the dot in the sidebar session row**

Open `frontend/src/app/components/sidebar/Sidebar.tsx`. Locate the loop rendering session entries (around lines 580-880 — there are several blocks for collapsed/expanded states). For each `<SessionRow>` JSX block, import and render the dot adjacent to the session title:

```tsx
import { StreamingIndicatorDot } from '@/features/chat/StreamingIndicatorDot'

// inside the row JSX:
<div className="flex items-center gap-1.5 min-w-0">
  <StreamingIndicatorDot sessionId={s.id} />
  <span className="truncate">{s.title || 'Untitled'}</span>
</div>
```

Apply consistently to every place a session title is rendered in this file. Run the existing sidebar tests to verify no layout regression:

```bash
cd frontend && pnpm vitest run src/app/components/sidebar
```

- [ ] **Step 7: Add the right-click "Stop generation" context menu entry**

In `frontend/src/app/components/sidebar/Sidebar.tsx`, find the existing context-menu code for session rows (the project uses a custom `FloatingMenu` or similar — search for `onContextMenu` in this file). Add a menu entry conditional on `useChatStore.getState().getStreamFor(s.id)?.isStreaming`:

```tsx
const isStreamingHere = useChatStore(
  useShallow((state) => Boolean(state.streamsBySession.get(s.id)?.isStreaming)),
)
// ...within the menu items:
{isStreamingHere && (
  <MenuItem
    onSelect={() => {
      const correlationId = useChatStore.getState()
        .streamsBySession.get(s.id)?.correlationId
      if (correlationId) {
        sendWsMessage({ type: 'chat.cancel', correlation_id: correlationId })
      }
    }}
  >
    Stop generation
  </MenuItem>
)}
```

Where `sendWsMessage` is the existing WS send helper used elsewhere in the sidebar. Adapt to the actual menu API (it may be `<button onClick=…>` inside the FloatingMenu).

- [ ] **Step 8: Place the dot in the persona switcher**

Open the persona-switcher file located in Step 1. For each persona row, render a dot if **any** session belonging to that persona is streaming. The cheapest signal is: subscribe to `streamsBySession`, and ask the chat-sessions list for the persona owner of each session id. If that turns out to be expensive, expose a memoised selector in chatStore:

```typescript
// Add to chatStore.ts near getStreamFor:
getStreamingSessionIds: () => string[]
// implementation:
getStreamingSessionIds: () => Array.from(get().streamsBySession.keys()),
```

Then in the persona switcher:

```tsx
const streamingSessionIds = useChatStore(
  useShallow((s) => Array.from(s.streamsBySession.keys())),
)
const personaIsStreaming = sessions.some(
  (sess) => streamingSessionIds.includes(sess.id) && sess.persona_id === persona.id,
)
{personaIsStreaming && <StreamingIndicatorDot sessionId={firstStreamingSessionForThisPersona} />}
```

(The dot itself takes one session id; pick the first streaming session for this persona — there is usually only one anyway.)

- [ ] **Step 9: Run frontend build and tests**

```bash
cd frontend && pnpm run build && pnpm vitest run
```

Expected: clean build, all tests pass.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/features/chat/StreamingIndicatorDot.tsx \
  frontend/src/features/chat/__tests__/StreamingIndicatorDot.test.tsx \
  frontend/src/app/components/sidebar/ \
  frontend/tailwind.config.cjs frontend/tailwind.config.ts \
  frontend/src/core/store/chatStore.ts
git commit -m "Add sidebar pulse-dot and Stop-generation menu for background completions"
```

---

## Task 9: Manual Verification at Staging

**Files:**
- None (verification only).

This task does not write code. It runs every manual-verification scenario in the spec end-to-end against the deployed branch.

- [ ] **Step 1: Bring up the dev stack**

```bash
docker compose up -d
```

Wait until backend, frontend, MongoDB, and Redis are all healthy. Tail the backend logs in another terminal:

```bash
docker compose logs -f backend
```

- [ ] **Step 2: Persona-switch survival**

1. Open the app, log in.
2. Pick a persona, ask a question that takes ≥30 s ("Write a 500-word essay on the history of compilers").
3. Once tokens are visibly streaming, switch personas.
4. Wait 60 s; switch back.
5. **Verify:** assistant message is fully present, status `completed`, no missing tokens. Check the backend log for an `inference completed` entry for this `correlation_id` after the persona switch happened.

- [ ] **Step 3: Sidebar pulse-dot present and stoppable**

1. Same setup; start a long answer.
2. Switch personas immediately.
3. **Verify:** the session row in the sidebar (under the original persona) has a pulse-dot next to its title.
4. Right-click that session row.
5. **Verify:** "Stop generation" menu item is present.
6. Click "Stop generation".
7. **Verify:** the dot disappears within ~1 s. The session, when opened, shows the truncated answer with `aborted` status.

- [ ] **Step 4: Same-session cancel still works**

1. Start a long answer in session X.
2. Wait for tokens.
3. While streaming, type and send another message in **the same session**.
4. **Verify:** the previous answer is cut at its current position with `aborted` status, and the new answer streams normally. Both messages are in the transcript in order.

- [ ] **Step 5: Cross-session non-interference**

1. Start a long answer in session A.
2. Open session B (different persona) and send a message there.
3. **Verify:** both inferences run in parallel. Session A finishes uncut. Session B answers normally.

- [ ] **Step 6: Tab reload survives**

1. Start a long answer.
2. Press `Ctrl+R` mid-stream.
3. After reload, navigate back to that session.
4. **Verify:** the answer either resumes streaming (Redis catchup) or is fully present in the transcript.

- [ ] **Step 7: Mobile background survives (PWA)**

1. On the iOS PWA, start a long answer.
2. Background the app for ~30 s.
3. Foreground it.
4. **Verify:** answer is intact (still streaming or completed).

- [ ] **Step 8: Voice + persona switch**

1. Enter continuous-voice mode in persona A.
2. Trigger a long answer with TTS audio playing.
3. While audio plays, switch to persona B.
4. **Verify:** TTS audio stops immediately.
5. **Verify:** the sidebar dot stays on persona A's session until inference finishes.
6. Switch back to A.
7. **Verify:** text answer is fully present in the transcript. No audio replays. Voice mode is off.

- [ ] **Step 9: Disconnect-extraction timing**

1. Start a long answer.
2. Close the browser tab while streaming.
3. Watch backend logs.
4. **Verify:** the assistant message persists with `completed` status. `disconnect_extraction` for this user fires **after** the inference's `inference_completed` log line, not at the 10-second grace mark.

- [ ] **Step 10: If anything failed**

Stop. Note the failure scenario. Do not push or merge. Return to the failing task and fix it.

- [ ] **Step 11: Commit a verification log**

If everything passes, write a brief verification log at `devdocs/plans/2026-05-07-background-completions-verified.md` listing each scenario and an "OK" timestamp, then:

```bash
git add devdocs/plans/2026-05-07-background-completions-verified.md
git commit -m "Verify background-completions end-to-end at staging"
```

---

## After All Tasks Pass

Per project convention (CLAUDE.md): merge the feature branch back to master. Do **not** push or merge from a subagent — only the orchestrating session does this, and only after the manual-verification task is green.

```bash
git checkout master
git merge --no-ff feat/background-completions
```
