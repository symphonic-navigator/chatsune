# Emoji Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase-I emoji picker — server-backed six-emoji LRU per user, lazy-loaded `@emoji-mart/react` picker mounted as an inline panel on mobile / anchored popover on desktop, in-text insertion with cursor-aware spacing rules.

**Architecture:** All persistence on the existing `users` document (single new field `recent_emojis`); LRU updates fire from the chat-send handler via `UserService.touch_recent_emojis`, propagated to all open user sessions through a new `USER_RECENT_EMOJIS_UPDATED` WebSocket topic. Frontend uses two small Zustand stores (open-state + recent list) and a single lazy-loaded picker component shared by desktop and mobile, switching layout on `useViewport().isMobile`.

**Tech Stack:** Python `regex` package (Unicode emoji classes — stdlib `re` cannot parse `\p{Extended_Pictographic}`); `@emoji-mart/react` + `@emoji-mart/data` (lazy import); existing infra: FastAPI, Pydantic v2, Zustand, Tailwind, the project's WebSocket event bus.

**Spec:** `devdocs/superpowers/specs/2026-04-25-emoji-picker-design.md`

---

## File Structure

### Backend — new files

- `backend/modules/chat/_emoji_extractor.py` — `extract_emojis(text)` pure-function utility.
- `tests/test_emoji_extractor.py` — host-runnable unit tests (no DB).
- `tests/test_user_recent_emojis.py` — host-runnable unit tests for `UserService._merge_lru`.
- `tests/test_user_recent_emojis_integration.py` — Docker-only integration test for `touch_recent_emojis`.

### Backend — modified files

- `pyproject.toml` (root) — add `regex>=2024.0.0`.
- `backend/pyproject.toml` — add `regex>=2024.0.0`.
- `backend/modules/user/_models.py` — add `recent_emojis` field + `DEFAULT_RECENT_EMOJIS` constant.
- `backend/modules/user/_repository.py` — add `update_recent_emojis(user_id, emojis)`.
- `backend/modules/user/__init__.py` — extend `UserService` with `touch_recent_emojis` + `_merge_lru` static helper.
- `backend/modules/chat/_handlers.py` — call `user_service.touch_recent_emojis` after send-message persists.
- `shared/topics.py` — add `USER_RECENT_EMOJIS_UPDATED`.
- `shared/events/auth.py` — add `RecentEmojisUpdatedEvent`.
- `shared/dtos/auth.py` — extend `UserDto` with `recent_emojis: list[str]`.

### Frontend — new files

- `frontend/src/features/chat/emojiPickerStore.ts` — open-state store.
- `frontend/src/features/chat/recentEmojisStore.ts` — server-driven LRU store.
- `frontend/src/features/chat/insertEmojiAtCursor.ts` — cursor-aware insertion utility.
- `frontend/src/features/chat/insertEmojiAtCursor.test.ts` — vitest unit tests.
- `frontend/src/features/chat/EmojiPickerPopover.tsx` — lazy picker + LRU header.
- `frontend/src/features/chat/LRUBar.tsx` — six-button recent row.

### Frontend — modified files

- `frontend/package.json` — add `@emoji-mart/react`, `@emoji-mart/data`.
- `frontend/src/core/types/events.ts` — add `USER_RECENT_EMOJIS_UPDATED` to `Topics`.
- `frontend/src/core/types/auth.ts` — extend `UserDto` interface with `recent_emojis: string[]`.
- `frontend/src/features/chat/ChatInput.tsx` — wire smile-button trigger, render `EmojiPickerPopover`, hook insertion + close-on-focus.
- `frontend/src/features/chat/cockpit/CockpitBar.tsx` — wire cockpit emoji button trigger and active state.
- `frontend/src/app/layouts/AppLayout.tsx` — subscribe `USER_RECENT_EMOJIS_UPDATED` to feed `recentEmojisStore`; hydrate store from `meApi.getMe()` on mount alongside the existing user fetch.

---

## Build Order

The backend ships first end-to-end (Tasks 1–7), so the frontend can run against a real WebSocket stream from the start. Frontend follows (Tasks 8–16). Manual verification closes the loop (Task 17).

---

## Task 1: Add `regex` dependency to both pyproject files

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add `regex>=2024.0.0` to root `pyproject.toml`**

Locate the `dependencies = [...]` block (the project-level dependencies, not `[dependency-groups].dev`). Insert in alphabetical order:

```toml
"regex>=2024.0.0",
```

- [ ] **Step 2: Add `regex>=2024.0.0` to `backend/pyproject.toml`**

Same package, same line, in the backend's own `dependencies` block. Both files MUST list the package — `backend/pyproject.toml` is what the Docker build uses (CLAUDE.md hard rule).

- [ ] **Step 3: Sync local environment**

```bash
cd /home/chris/workspace/chatsune
uv sync
```

Expected: succeeds with `regex` resolved.

- [ ] **Step 4: Smoke-test the import**

```bash
cd /home/chris/workspace/chatsune
uv run python -c "import regex; print(regex.__version__)"
```

Expected: prints a version string ≥ 2024.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml backend/pyproject.toml uv.lock
git commit -m "Add regex dependency for emoji extraction"
```

---

## Task 2: Emoji extractor (TDD)

**Files:**
- Create: `backend/modules/chat/_emoji_extractor.py`
- Create: `tests/test_emoji_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_emoji_extractor.py`:

```python
from backend.modules.chat._emoji_extractor import extract_emojis


def test_extract_emojis_returns_empty_list_for_plain_text():
    assert extract_emojis("Hello world, no emoji here") == []


def test_extract_emojis_returns_single_emoji():
    assert extract_emojis("Hello 👋") == ["👋"]


def test_extract_emojis_preserves_order():
    assert extract_emojis("First 🔥 second 🤘 third 😊") == ["🔥", "🤘", "😊"]


def test_extract_emojis_handles_skin_tone_modifier_as_one_unit():
    # 👍🏽 = 👍 (U+1F44D) + skin-tone modifier (U+1F3FD)
    assert extract_emojis("nice 👍🏽 work") == ["👍🏽"]


def test_extract_emojis_handles_zwj_family_as_one_unit():
    # Family emoji = man + ZWJ + woman + ZWJ + girl + ZWJ + boy
    assert extract_emojis("our family 👨‍👩‍👧‍👦 yes") == [
        "👨‍👩‍👧‍👦"
    ]


def test_extract_emojis_returns_duplicates_in_order():
    assert extract_emojis("😂😂lol😂") == ["😂", "😂", "😂"]


def test_extract_emojis_empty_input():
    assert extract_emojis("") == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run pytest tests/test_emoji_extractor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.modules.chat._emoji_extractor'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/modules/chat/_emoji_extractor.py`:

```python
"""Extract Unicode emoji sequences from a chat message.

Uses the third-party `regex` package because the stdlib `re` does not
support `\\p{Extended_Pictographic}` or other Unicode property classes.
"""
import regex

# An emoji "unit" is a base pictographic optionally followed by:
#   - one skin-tone modifier (\p{EMod}), or
#   - one or more ZWJ-joined pictographic continuations.
_EMOJI_RE = regex.compile(
    r"\p{Extended_Pictographic}(?:\p{EMod}|‍\p{Extended_Pictographic})*"
)


def extract_emojis(text: str) -> list[str]:
    """Return emojis in order of appearance, preserving skin-tone modifiers
    and ZWJ-joined sequences as single units."""
    return _EMOJI_RE.findall(text)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run pytest tests/test_emoji_extractor.py -v
```

Expected: all seven tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_emoji_extractor.py tests/test_emoji_extractor.py
git commit -m "Add emoji extractor utility with skin-tone and ZWJ support"
```

---

## Task 3: User document — `recent_emojis` field + default set

**Files:**
- Modify: `backend/modules/user/_models.py`

- [ ] **Step 1: Add the default constant and the field**

At the top of the file (after imports, before any class), add:

```python
DEFAULT_RECENT_EMOJIS: tuple[str, ...] = ("👍", "❤️", "😂", "🤘", "😊", "🔥")
```

Inside `class UserDocument(BaseModel)`, add the field (near the other simple-type fields, e.g. after `must_change_password`):

```python
    recent_emojis: list[str] = Field(default_factory=lambda: list(DEFAULT_RECENT_EMOJIS))
```

`default_factory` returns a fresh list every time so two new users do not share the same mutable list.

- [ ] **Step 2: Smoke-test the model loads**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run python -c "
from backend.modules.user._models import UserDocument, DEFAULT_RECENT_EMOJIS
from datetime import datetime

# Existing-shape doc (no recent_emojis field) — must default-fill cleanly
doc = UserDocument(
    _id='u1', username='x', email='x@y.z', display_name='X',
    password_hash='', role='user',
    created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
)
assert doc.recent_emojis == list(DEFAULT_RECENT_EMOJIS), doc.recent_emojis
print('OK', doc.recent_emojis)
"
```

Expected: prints `OK ['👍', '❤️', '😂', '🤘', '😊', '🔥']`.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/user/_models.py
git commit -m "Add recent_emojis field with default set to UserDocument"
```

---

## Task 4: Repository write method

**Files:**
- Modify: `backend/modules/user/_repository.py`

- [ ] **Step 1: Add the method**

Locate the existing `class UsersRepository` (or whatever it is named in `_repository.py`). Add a new method alongside the other update methods:

```python
    async def update_recent_emojis(self, user_id: str, emojis: list[str]) -> None:
        """Atomic replace of the user's recent_emojis list.

        The caller is responsible for already deduping and capping at the
        intended size — this method performs no validation."""
        await self._collection.update_one(
            {"_id": user_id},
            {"$set": {
                "recent_emojis": emojis,
                "updated_at": datetime.utcnow(),
            }},
        )
```

Make sure `from datetime import datetime` is at the top — it usually already is in repository files; if not, add it.

If the repository's collection attribute is named differently (e.g. `self.collection` or `self._users`), adjust accordingly. Check the file to follow the existing pattern.

- [ ] **Step 2: Type-check the file**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run python -m py_compile backend/modules/user/_repository.py
```

Expected: no output (clean).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/user/_repository.py
git commit -m "Add update_recent_emojis to user repository"
```

---

## Task 5: Shared contracts — Topic, Event, DTO

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/auth.py`
- Modify: `shared/dtos/auth.py`

- [ ] **Step 1: Add the topic**

In `shared/topics.py`, locate the block of `USER_*` topics and add:

```python
USER_RECENT_EMOJIS_UPDATED = "user.recent_emojis.updated"
```

If `topics.py` uses a class with attributes, add it as a class attribute next to the others; if it is a flat module of constants, add it as a top-level constant. Match the existing style.

- [ ] **Step 2: Add the event class**

In `shared/events/auth.py`, append:

```python
class RecentEmojisUpdatedEvent(BaseModel):
    """Published when a user's recent-emoji LRU changes (max six entries)."""
    type: Literal["user.recent_emojis.updated"] = "user.recent_emojis.updated"
    user_id: str
    emojis: list[str]
```

If `Literal` is not yet imported, add `from typing import Literal` at the top alongside existing typing imports.

- [ ] **Step 3: Extend the DTO**

In `shared/dtos/auth.py`, locate `class UserDto(BaseModel)`. Add at the end of the field list, before `model_config` if any:

```python
    recent_emojis: list[str] = Field(default_factory=list)
```

Make sure `Field` is imported (it usually is; if not, `from pydantic import Field`).

- [ ] **Step 4: Smoke-test the imports**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run python -c "
from shared.topics import USER_RECENT_EMOJIS_UPDATED  # or Topics.USER_...
from shared.events.auth import RecentEmojisUpdatedEvent
from shared.dtos.auth import UserDto

ev = RecentEmojisUpdatedEvent(user_id='u1', emojis=['🔥'])
print('event.type =', ev.type, 'topic =', USER_RECENT_EMOJIS_UPDATED)
assert ev.type == USER_RECENT_EMOJIS_UPDATED
"
```

Adjust the import to match your topic style (constant vs. `Topics.*`). Expected: prints values and the assert holds.

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/events/auth.py shared/dtos/auth.py
git commit -m "Add USER_RECENT_EMOJIS_UPDATED contract (topic + event + DTO field)"
```

---

## Task 6: UserService — `_merge_lru` + `touch_recent_emojis` (TDD)

**Files:**
- Modify: `backend/modules/user/__init__.py`
- Create: `tests/test_user_recent_emojis.py`

- [ ] **Step 1: Write the failing unit tests for `_merge_lru`**

Create `tests/test_user_recent_emojis.py`:

```python
from backend.modules.user import UserService


def test_merge_lru_front_loads_new_emoji():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["x"],
        max_size=6,
    )
    assert result == ["x", "a", "b", "c", "d", "e"]


def test_merge_lru_dedupes_within_incoming():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["x", "x", "y"],
        max_size=6,
    )
    assert result == ["x", "y", "a", "b", "c", "d"]


def test_merge_lru_moves_existing_emoji_to_front():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["c"],
        max_size=6,
    )
    assert result == ["c", "a", "b", "d", "e", "f"]


def test_merge_lru_caps_at_max_size():
    result = UserService._merge_lru(
        current=["a", "b", "c", "d", "e", "f"],
        incoming=["x", "y", "z"],
        max_size=6,
    )
    assert result == ["x", "y", "z", "a", "b", "c"]


def test_merge_lru_handles_empty_incoming():
    result = UserService._merge_lru(
        current=["a", "b", "c"],
        incoming=[],
        max_size=6,
    )
    assert result == ["a", "b", "c"]


def test_merge_lru_handles_empty_current():
    result = UserService._merge_lru(
        current=[],
        incoming=["x", "y"],
        max_size=6,
    )
    assert result == ["x", "y"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run pytest tests/test_user_recent_emojis.py -v
```

Expected: FAIL — either `_merge_lru` does not exist, or import error.

- [ ] **Step 3: Add `_merge_lru` and `touch_recent_emojis` to UserService**

Open `backend/modules/user/__init__.py`. Locate the `UserService` class. Add the two methods (typically at the end of the class):

```python
    @staticmethod
    def _merge_lru(current: list[str], incoming: list[str], max_size: int) -> list[str]:
        """Front-load `incoming` (in order, deduped against later occurrences),
        then append remaining items from `current`. Cap at `max_size`."""
        seen: set[str] = set()
        merged: list[str] = []
        for emoji in [*incoming, *current]:
            if emoji in seen:
                continue
            seen.add(emoji)
            merged.append(emoji)
            if len(merged) >= max_size:
                break
        return merged

    async def touch_recent_emojis(self, user_id: str, emojis_in_text: list[str]) -> None:
        """Move freshly-used emojis to the front of the user's LRU.

        Idempotent — duplicate entries in `emojis_in_text` are tolerated.
        No-op when the input is empty or when the resulting list is
        unchanged from the user's current list."""
        if not emojis_in_text:
            return
        user = await self._repository.get_by_id(user_id)
        if user is None:
            return
        new_list = self._merge_lru(user.recent_emojis, emojis_in_text, max_size=6)
        if new_list == user.recent_emojis:
            return
        await self._repository.update_recent_emojis(user_id, new_list)
        await self._event_bus.publish(
            USER_RECENT_EMOJIS_UPDATED,
            RecentEmojisUpdatedEvent(user_id=user_id, emojis=new_list),
            scope=f"user:{user_id}",
        )
```

Add the imports at the top of the file:

```python
from shared.topics import USER_RECENT_EMOJIS_UPDATED  # or `Topics` style
from shared.events.auth import RecentEmojisUpdatedEvent
```

Verify the repository attribute is named `self._repository` (or adjust). Verify the event-bus method signature matches the existing pattern in this file (some codebases use `event_bus.publish(topic, event)` without `scope`; if `scope=` is not the right kwarg, mirror what other UserService methods already do).

- [ ] **Step 4: Run unit tests to verify they pass**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run pytest tests/test_user_recent_emojis.py -v
```

Expected: all six tests PASS.

- [ ] **Step 5: Write the integration test (Docker-only)**

Create `tests/test_user_recent_emojis_integration.py`:

```python
"""Integration test for UserService.touch_recent_emojis.

Requires MongoDB replica-set + Redis. Runs inside Docker Compose only.
On the host, this file is in the standard ignore list.
"""
import pytest

# Use whatever fixture pattern other DB-dependent tests in this repo use —
# typically a `user_service` fixture from conftest.py with `test_db` and a
# clean-slate `user_keys` setup. Adjust imports/fixtures to match what is
# already in `backend/tests/conftest.py` or `tests/conftest.py`.

pytestmark = pytest.mark.asyncio


async def test_touch_recent_emojis_persists_and_publishes(
    user_service, captured_events, seed_user
):
    user = await seed_user(username="alice")

    await user_service.touch_recent_emojis(user.id, ["🚀", "🎯"])

    refreshed = await user_service.get_by_id(user.id)
    assert refreshed.recent_emojis[:2] == ["🚀", "🎯"]
    assert len(refreshed.recent_emojis) == 6

    published = [
        e for e in captured_events
        if e.topic == "user.recent_emojis.updated"
    ]
    assert len(published) == 1
    assert published[0].payload["user_id"] == user.id
    assert published[0].payload["emojis"][:2] == ["🚀", "🎯"]


async def test_touch_recent_emojis_no_change_does_not_publish(
    user_service, captured_events, seed_user
):
    user = await seed_user(username="bob")
    # First call sets the LRU
    await user_service.touch_recent_emojis(user.id, ["🚀"])
    captured_events.clear()
    # Second call with the same emoji and no movement → no event
    await user_service.touch_recent_emojis(user.id, ["🚀"])
    published = [
        e for e in captured_events
        if e.topic == "user.recent_emojis.updated"
    ]
    assert published == []
```

If the fixture names in this repo differ (`user_service`, `captured_events`, `seed_user`), inspect `tests/conftest.py` or `backend/tests/conftest.py` and adapt. Do not invent fixtures — use what is already wired.

- [ ] **Step 6: Run the integration test in Docker**

```bash
cd /home/chris/workspace/chatsune
docker compose up -d mongo redis backend
docker compose exec backend pytest tests/test_user_recent_emojis_integration.py -v
```

Expected: both tests PASS.

If fixtures need adjustment, iterate until they pass. Do NOT mark the test as `xfail` or `skip` — the LRU behaviour must be verified end-to-end.

- [ ] **Step 7: Add the integration file to the host-ignore guidance**

The host-pytest ignore list in `feedback_db_tests_on_host.md` lists four files. We are adding a fifth (`tests/test_user_recent_emojis_integration.py`) but we do not edit that memory file from code — it is a personal note. Just be aware that future host-runs need:

```bash
PYTHONPATH=. uv run pytest backend/ shared/ \
  --ignore=backend/tests/integration/test_community_e2e.py \
  --ignore=backend/tests/modules/llm/test_connections_repo.py \
  --ignore=backend/tests/modules/llm/test_homelab_self_connection.py \
  --ignore=backend/tests/modules/llm/test_homelabs.py \
  --ignore=tests/test_user_recent_emojis_integration.py
```

(No file change in this step — this is documentation only.)

- [ ] **Step 8: Commit**

```bash
git add backend/modules/user/__init__.py \
        tests/test_user_recent_emojis.py \
        tests/test_user_recent_emojis_integration.py
git commit -m "Add UserService.touch_recent_emojis with LRU merge and event publish"
```

---

## Task 7: Chat-handler hook

**Files:**
- Modify: `backend/modules/chat/_handlers.py`

- [ ] **Step 1: Locate the send-message handler**

Find the handler that processes a user message after it is persisted but before LLM inference is dispatched. Common names: `handle_send_message`, `_persist_user_message`, `on_user_message`. The handler already has access to `user_id` (from auth context) and `message_text` (the body).

- [ ] **Step 2: Add the hook**

Insert this block immediately after the message is successfully persisted to MongoDB and before LLM inference is started:

```python
        try:
            from backend.modules.chat._emoji_extractor import extract_emojis
            emojis = extract_emojis(message_text)
            if emojis:
                await self._user_service.touch_recent_emojis(user_id, emojis)
        except Exception as exc:
            logger.warning(
                "recent_emojis_update_failed",
                extra={"user_id": user_id, "error": str(exc)},
            )
```

The local import keeps `_emoji_extractor` out of the chat-module's startup graph (it is only needed when there is a message). The `try/except` ensures a Mongo or event-bus blip cannot block the chat flow — LRU is comfort, not critical.

If the handler does not already have access to `self._user_service`, wire it through the chat module's existing service-resolver pattern (mirror how `self._persona_service` or similar collaborators are obtained). Do not import the user repository directly — that violates module boundaries (CLAUDE.md hard rule).

- [ ] **Step 3: Type-check**

```bash
cd /home/chris/workspace/chatsune
PYTHONPATH=. uv run python -m py_compile backend/modules/chat/_handlers.py
```

Expected: no output.

- [ ] **Step 4: Smoke-test end-to-end in Docker**

```bash
cd /home/chris/workspace/chatsune
docker compose up -d
# Open the app, log in, send a chat message containing two emojis,
# then inspect the user document to confirm recent_emojis updated.
docker compose exec mongo mongosh chatsune --eval \
  'db.users.findOne({}, {recent_emojis: 1, username: 1})'
```

Expected: the active user's `recent_emojis` shows the two emojis at the front.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_handlers.py
git commit -m "Touch user recent_emojis on chat send"
```

---

## Task 8: Frontend dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the picker packages**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm add @emoji-mart/react @emoji-mart/data emoji-mart
```

`emoji-mart` is the runtime peer that `@emoji-mart/react` depends on. Pin nothing manually — pnpm picks current stable.

- [ ] **Step 2: Verify the build still passes**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: build succeeds. Bundle size warning is acceptable — picker is lazy-loaded so it does not enter the initial chunk.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add @emoji-mart picker dependencies (lazy-loaded)"
```

---

## Task 9: Frontend Topics + UserDto mirror

**Files:**
- Modify: `frontend/src/core/types/events.ts`
- Modify: `frontend/src/core/types/auth.ts`

- [ ] **Step 1: Add the topic to the frontend mirror**

In `frontend/src/core/types/events.ts`, add to the `Topics` const:

```ts
  USER_RECENT_EMOJIS_UPDATED: "user.recent_emojis.updated",
```

Place it next to the other `USER_*` entries.

- [ ] **Step 2: Extend the UserDto interface**

In `frontend/src/core/types/auth.ts`, add to the `UserDto` interface:

```ts
  recent_emojis: string[]
```

Place it after `updated_at`.

- [ ] **Step 3: Type-check the frontend**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean. Existing places that build a UserDto literal (mocks, fixtures, test factories) may complain about the missing field — fix each call site by adding `recent_emojis: []` to the literal.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/types/events.ts frontend/src/core/types/auth.ts
git commit -m "Mirror USER_RECENT_EMOJIS_UPDATED topic and UserDto field on frontend"
```

---

## Task 10: `insertEmojiAtCursor` (TDD)

**Files:**
- Create: `frontend/src/features/chat/insertEmojiAtCursor.ts`
- Create: `frontend/src/features/chat/insertEmojiAtCursor.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/chat/insertEmojiAtCursor.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { insertEmojiAtCursor } from './insertEmojiAtCursor'

function makeTextarea(value: string, selectionStart: number, selectionEnd = selectionStart) {
  const ta = document.createElement('textarea')
  ta.value = value
  ta.selectionStart = selectionStart
  ta.selectionEnd = selectionEnd
  return ta
}

describe('insertEmojiAtCursor', () => {
  it('inserts at empty input with no surrounding spaces', () => {
    const ta = makeTextarea('', 0)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: '😊', cursor: 2 })
  })

  it('inserts at end of text-only input — leading space, no trailing', () => {
    const ta = makeTextarea('hello', 5)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊', cursor: 8 })
  })

  it('inserts at start of text-only input — no leading, trailing space', () => {
    const ta = makeTextarea('hello', 0)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: '😊 hello', cursor: 3 })
  })

  it('inserts in the middle of text — both spaces', () => {
    const ta = makeTextarea('helloworld', 5)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊 world', cursor: 9 })
  })

  it('does not double-space after existing trailing space', () => {
    const ta = makeTextarea('hello ', 6)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊', cursor: 8 })
  })

  it('does not space between two emojis', () => {
    const ta = makeTextarea('😊', 2)
    expect(insertEmojiAtCursor(ta, '🔥')).toEqual({ value: '😊🔥', cursor: 4 })
  })

  it('does not space when previous char is whitespace', () => {
    const ta = makeTextarea('a\n', 2)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'a\n😊', cursor: 5 })
  })

  it('replaces selected range', () => {
    const ta = makeTextarea('helloXXworld', 5, 7)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊 world', cursor: 9 })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/chat/insertEmojiAtCursor.test.ts
```

Expected: FAIL with "Cannot find module './insertEmojiAtCursor'".

- [ ] **Step 3: Write the implementation**

Create `frontend/src/features/chat/insertEmojiAtCursor.ts`:

```ts
const EMOJI_RE = /\p{Extended_Pictographic}/u

/** Insert an emoji at the textarea's caret with Chatsune's spacing rules:
 *  add a leading space iff the previous char is non-empty, non-whitespace,
 *  non-emoji; add a trailing space iff the next char is non-empty,
 *  non-whitespace, non-emoji. Returns the new value and the resulting
 *  caret position so the caller can re-apply selection after re-render. */
export function insertEmojiAtCursor(
  textarea: HTMLTextAreaElement,
  emoji: string,
): { value: string; cursor: number } {
  const { value, selectionStart, selectionEnd } = textarea
  const before = value.slice(0, selectionStart)
  const after = value.slice(selectionEnd)

  const prevChar = before.slice(-1)
  const nextChar = after.slice(0, 1)

  const needsLead =
    prevChar !== '' && !/\s/.test(prevChar) && !EMOJI_RE.test(prevChar)
  const needsTrail =
    nextChar !== '' && !/\s/.test(nextChar) && !EMOJI_RE.test(nextChar)

  const insertion = (needsLead ? ' ' : '') + emoji + (needsTrail ? ' ' : '')
  const newValue = before + insertion + after
  const newCursor = before.length + insertion.length
  return { value: newValue, cursor: newCursor }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/chat/insertEmojiAtCursor.test.ts
```

Expected: all eight tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/insertEmojiAtCursor.ts \
        frontend/src/features/chat/insertEmojiAtCursor.test.ts
git commit -m "Add insertEmojiAtCursor with cursor-aware spacing rules"
```

---

## Task 11: Emoji-picker open-state store

**Files:**
- Create: `frontend/src/features/chat/emojiPickerStore.ts`

- [ ] **Step 1: Write the store**

Create `frontend/src/features/chat/emojiPickerStore.ts`:

```ts
import { create } from 'zustand'

interface EmojiPickerState {
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
}

export const useEmojiPickerStore = create<EmojiPickerState>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
}))
```

- [ ] **Step 2: Type-check**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/emojiPickerStore.ts
git commit -m "Add emoji picker open-state store"
```

---

## Task 12: Recent-emojis store + initial hydration + WS subscription

**Files:**
- Create: `frontend/src/features/chat/recentEmojisStore.ts`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Write the store**

Create `frontend/src/features/chat/recentEmojisStore.ts`:

```ts
import { create } from 'zustand'

interface RecentEmojisState {
  emojis: string[]
  set: (emojis: string[]) => void
}

export const useRecentEmojisStore = create<RecentEmojisState>((set) => ({
  emojis: [],
  set: (emojis) => set({ emojis }),
}))
```

- [ ] **Step 2: Wire up initial hydration in AppLayout**

Open `frontend/src/app/layouts/AppLayout.tsx`. Locate the place where the current user is fetched (look for `meApi.getMe()` or the `USER_PROFILE_UPDATED` subscription block — the file already has user hydration logic).

Where the current `UserDto` is available after `meApi.getMe()` resolves, add:

```tsx
import { useRecentEmojisStore } from '../../features/chat/recentEmojisStore'

// inside the effect that handles the initial me-fetch:
useRecentEmojisStore.getState().set(user.recent_emojis ?? [])
```

If hydration is structured as a `useEffect` that calls `meApi.getMe()` and stores the result in a `userStore`, mirror that flow — set both stores when the user payload arrives.

- [ ] **Step 3: Wire up the WS subscription**

Still in `AppLayout.tsx`, near the existing `useEventBus(Topics.USER_PROFILE_UPDATED)` subscription, add:

```tsx
const { latest: recentEmojisUpdate } = useEventBus(Topics.USER_RECENT_EMOJIS_UPDATED)

useEffect(() => {
  if (!recentEmojisUpdate?.payload) return
  const emojis = (recentEmojisUpdate.payload as { emojis?: string[] }).emojis
  if (Array.isArray(emojis)) {
    useRecentEmojisStore.getState().set(emojis)
  }
}, [recentEmojisUpdate])
```

This mirrors the existing `USER_PROFILE_UPDATED` pattern in this file — keep style consistent.

- [ ] **Step 4: Type-check**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/recentEmojisStore.ts \
        frontend/src/app/layouts/AppLayout.tsx
git commit -m "Add recentEmojisStore with initial hydration and WS subscription"
```

---

## Task 13: LRUBar component

**Files:**
- Create: `frontend/src/features/chat/LRUBar.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/chat/LRUBar.tsx`:

```tsx
interface Props {
  emojis: string[]
  onSelect: (emoji: string) => void
}

export function LRUBar({ emojis, onSelect }: Props) {
  if (emojis.length === 0) return null
  return (
    <div className="flex items-center gap-1 rounded-t-lg border-b border-white/8 bg-[#1a1625] px-2 py-1.5">
      <span className="mr-2 text-[10px] uppercase tracking-wider text-white/40">
        Recent
      </span>
      {emojis.map((emoji) => (
        <button
          key={emoji}
          type="button"
          onClick={() => onSelect(emoji)}
          aria-label={`Insert ${emoji}`}
          className="rounded-md px-1.5 py-0.5 text-lg transition-colors hover:bg-white/10"
        >
          {emoji}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/LRUBar.tsx
git commit -m "Add LRUBar with six-emoji recent row"
```

---

## Task 14: EmojiPickerPopover (lazy picker + LRU header)

**Files:**
- Create: `frontend/src/features/chat/EmojiPickerPopover.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/chat/EmojiPickerPopover.tsx`:

```tsx
import { Suspense, lazy, useEffect, useRef } from 'react'
import { useViewport } from '../../core/hooks/useViewport'
import { useRecentEmojisStore } from './recentEmojisStore'
import { LRUBar } from './LRUBar'

const Picker = lazy(() => import('@emoji-mart/react').then((m) => ({ default: m.default })))
const dataPromise = import('@emoji-mart/data')

interface Props {
  onSelect: (emoji: string) => void
  onClose: () => void
}

function PickerSkeleton() {
  return (
    <div className="h-[360px] w-[320px] animate-pulse rounded-lg border border-white/8 bg-white/4" />
  )
}

export function EmojiPickerPopover({ onSelect, onClose }: Props) {
  const { isMobile } = useViewport()
  const recent = useRecentEmojisStore((s) => s.emojis)
  const containerRef = useRef<HTMLDivElement>(null)

  // Outside click closes
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current) return
      if (!containerRef.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [onClose])

  // Escape closes
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const containerClass = isMobile
    ? 'absolute bottom-full left-0 right-0 mb-2 z-40'
    : 'absolute bottom-full right-0 mb-2 z-40'

  return (
    <div ref={containerRef} className={containerClass}>
      <div className="overflow-hidden rounded-lg border border-white/10 bg-[#0f0d16] shadow-xl">
        <LRUBar emojis={recent} onSelect={onSelect} />
        <Suspense fallback={<PickerSkeleton />}>
          <Picker
            data={dataPromise}
            onEmojiSelect={(e: { native: string }) => onSelect(e.native)}
            theme="dark"
            set="native"
            previewPosition="none"
            skinTonePosition="search"
            categories={['people', 'nature', 'foods', 'activity', 'places', 'objects', 'symbols', 'flags']}
          />
        </Suspense>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean. If the `@emoji-mart/react` types complain about `data: Promise`, the wrapper accepts a promise — if your version's typings are stricter, change to `data: dataPromise as any` with a one-line comment explaining the typing gap.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/EmojiPickerPopover.tsx
git commit -m "Add EmojiPickerPopover with lazy emoji-mart and LRU header"
```

---

## Task 15: ChatInput integration

**Files:**
- Modify: `frontend/src/features/chat/ChatInput.tsx`

- [ ] **Step 1: Wire the smile-button trigger**

Replace the existing no-op `onClick={() => {}}` on the desktop smile-button (the `<button>` inside the `relative flex-1` wrapper) with:

```tsx
onClick={() => useEmojiPickerStore.getState().toggle()}
```

Add the imports near the other imports at the top of the file:

```tsx
import { useEmojiPickerStore } from './emojiPickerStore'
import { EmojiPickerPopover } from './EmojiPickerPopover'
import { insertEmojiAtCursor } from './insertEmojiAtCursor'
```

- [ ] **Step 2: Add the picker render and the insert handler**

Inside the component body, near the existing `useState`/`useRef` hooks:

```tsx
const isPickerOpen = useEmojiPickerStore((s) => s.isOpen)
const closePicker = useEmojiPickerStore((s) => s.close)

const handleEmojiSelect = useCallback((emoji: string) => {
  const ta = textareaRef.current
  if (!ta) return
  const { value, cursor } = insertEmojiAtCursor(ta, emoji)
  setText(value)
  requestAnimationFrame(() => {
    ta.focus()
    ta.setSelectionRange(cursor, cursor)
  })
}, [])
```

Inside the relative wrapper that holds the textarea (the `<div className="relative flex flex-1 items-end">`), at the end of the children, add:

```tsx
{isPickerOpen && (
  <EmojiPickerPopover
    onSelect={handleEmojiSelect}
    onClose={closePicker}
  />
)}
```

(The popover positions itself with `absolute bottom-full` so it lifts above the input.)

- [ ] **Step 3: Add focus-close on the textarea**

On the `<textarea ...>` element, add an `onFocus` handler:

```tsx
onFocus={() => closePicker()}
```

- [ ] **Step 4: Type-check and build**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit && pnpm run build
```

Expected: both clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/ChatInput.tsx
git commit -m "Wire emoji picker into ChatInput with cursor insertion and focus-close"
```

---

## Task 16: CockpitBar integration

**Files:**
- Modify: `frontend/src/features/chat/cockpit/CockpitBar.tsx`

- [ ] **Step 1: Wire the cockpit emoji button**

Replace the placeholder `onClick={() => {}}` on the mobile emoji `CockpitButton` with the toggle, and reflect the open state.

Add the import at the top of the file:

```tsx
import { useEmojiPickerStore } from '../emojiPickerStore'
```

Inside the component, before the `return`, read the open state:

```tsx
const isPickerOpen = useEmojiPickerStore((s) => s.isOpen)
```

Update the cockpit emoji button to:

```tsx
{isMobile && (
  <CockpitButton
    icon="😊"
    state={isPickerOpen ? 'active' : 'idle'}
    accent="neutral"
    label="Insert emoji"
    onClick={() => useEmojiPickerStore.getState().toggle()}
  />
)}
```

- [ ] **Step 2: Type-check and build**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit && pnpm run build
```

Expected: both clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/cockpit/CockpitBar.tsx
git commit -m "Wire cockpit emoji button to picker toggle with active state"
```

---

## Task 17: Manual verification

**Files:**
- None (no code changes; this validates the running system end-to-end).

- [ ] **Step 1: Run the stack**

```bash
cd /home/chris/workspace/chatsune
docker compose up -d
cd frontend && pnpm dev
```

Open `http://localhost:5173` (or whatever the dev server prints).

- [ ] **Step 2: Desktop Chromium 1920×1080 — basic insert**

Log in as an existing user. Click into the chat input. Click the small smile button on the right inside the input field. Picker appears anchored above. Type "abcdef", place the cursor between "abc" and "def" by clicking, then click 😀 in the picker. Expected: `abc 😀 def` in the input. Picker stays open.

- [ ] **Step 3: Desktop Firefox — skin tone + send**

Repeat in Firefox. Open the picker, click the skin-tone selector next to the search field, choose a darker tone, then click 👍. Expected: `👍🏿` (or matching skin tone) appears in the input. Send the message. Open the picker again — the LRU bar shows your skin-toned 👍🏿 in the first slot.

- [ ] **Step 4: Mobile Chromium 375×667 — cockpit trigger and focus-close**

Open Chromium DevTools, switch to responsive mode, set viewport to 375×667 (iPhone SE). Tap the 😊 in the cockpit. Picker appears above the cockpit, no backdrop. Tap a 🔥. Tap back into the prompt input — the picker closes.

- [ ] **Step 5: Multi-tab live update**

Open two browser tabs as the same user. In tab A, send `Hi 🚀`. Switch to tab B, open the picker. Expected: 🚀 sits at the front of the LRU bar without any reload of tab B.

- [ ] **Step 6: Brand-new user default set**

Create a new user (or wipe the recent_emojis on an existing user via mongosh). Open the picker. Expected: LRU bar shows `👍 ❤️ 😂 🤘 😊 🔥` in that order. Send a message containing 🥳. Expected: 🥳 is now first; 🔥 falls off the end.

- [ ] **Step 7: Disconnect resilience**

With the picker open, switch DevTools → Network → Offline. Type a message containing 🌟 and try to send. The send is held by the existing offline-queue logic. Switch back online, the message goes through, the LRU updates with 🌟 at the front.

- [ ] **Step 8: Final commit (no code, marker only)**

If any small fixes were applied during manual testing, commit each as a separate logical step. If everything passed without changes, no commit is needed for this task.

---

## Self-Review Checklist (already applied)

- **Spec coverage:** Backend extractor (T2), document field (T3), repository (T4), shared contracts (T5), service (T6), chat hook (T7), frontend mirrors (T8–9), insertion (T10), stores (T11–12), LRU bar (T13), picker (T14), ChatInput integration (T15), CockpitBar integration (T16), manual verification (T17).
- **No placeholders:** every step contains exact code, exact commands, exact paths.
- **Type consistency:** `recent_emojis` is `list[str]` in Pydantic, `string[]` in TS, `emojis` is the payload key in the event everywhere.
- **Module boundaries:** chat-handler calls the public `UserService.touch_recent_emojis`, never the user repository — verified per CLAUDE.md hard rule.
- **Migration story:** `default_factory` covers existing-doc reads; no wipe required (CLAUDE.md beta rule).
- **Both pyproject.toml files updated** for the `regex` dependency.
