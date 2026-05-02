# Master System Prompt in Internal LLM Calls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject the admin master system prompt into every internal server-side LLM call (memory extraction, memory consolidation, title generation, vision fallback) as a real `system`-role message, so admin-set guardrail-loosening directives apply to those flows just like they do in chat.

**Architecture:** Add a single helper to the settings module's public API that returns the master prompt as a ready-to-prepend `CompletionMessage` (wrapped in `<systeminstructions priority="highest">`) plus its raw text for token-budget arithmetic. Each of the four call-sites prepends this message when the admin prompt is set, falling back byte-for-byte to current behaviour when it is not. Vision fallback is additionally restructured so its functional instruction lives in the user-role message together with the image, freeing the system role for the master prompt.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest with `pytest.mark.asyncio`, MongoDB (settings collection — unchanged).

**Spec:** `devdocs/specs/2026-05-02-master-prompt-internal-llm-calls-design.md`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/modules/settings/__init__.py` | Modify | Export new `AdminSystemPrompt` dataclass and `get_admin_system_message()` async function as part of the public API. |
| `backend/jobs/handlers/_memory_extraction.py` | Modify | Prepend admin system message to the LLM request; include admin text in budget reservation and token accounting. |
| `backend/jobs/handlers/_memory_consolidation.py` | Modify | Same as memory extraction. |
| `backend/jobs/handlers/_title_generation.py` | Modify | Same, with admin message inserted before the existing conversation history + instruction tail. |
| `backend/modules/chat/_vision_fallback.py` | Modify | Restructure messages: text instruction + image become a single user-role message; admin master prompt becomes the (optional) leading system-role message. Rename `_VISION_FALLBACK_SYSTEM_PROMPT` to `_VISION_FALLBACK_USER_INSTRUCTION` and reword to first-person. |
| `tests/test_settings_admin_prompt.py` | Create | Unit tests for the new helper. |
| `tests/test_memory_extraction_handler_admin_prompt.py` | Create | Integration tests for admin-prompt injection in the extraction handler. |
| `tests/test_memory_consolidation_handler_admin_prompt.py` | Create | Integration tests for admin-prompt injection in the consolidation handler. |
| `tests/test_title_generation_handler.py` | Modify | Append two tests for admin-prompt injection (set vs unset). |
| `tests/test_vision_fallback_admin_prompt.py` | Create | Integration tests for admin-prompt injection and the restructured message layout. |

---

## Task 1: Settings module helper — `AdminSystemPrompt` and `get_admin_system_message()`

**Files:**
- Create: `tests/test_settings_admin_prompt.py`
- Modify: `backend/modules/settings/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_admin_prompt.py`:

```python
"""Unit tests for the admin master system prompt helper."""

from unittest.mock import patch

import pytest

from backend.modules.settings import AdminSystemPrompt, get_admin_system_message


@pytest.mark.asyncio
async def test_returns_none_when_setting_unset():
    with patch("backend.modules.settings.get_setting", return_value=None):
        result = await get_admin_system_message()
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_setting_empty():
    with patch("backend.modules.settings.get_setting", return_value=""):
        result = await get_admin_system_message()
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_setting_whitespace_only():
    with patch("backend.modules.settings.get_setting", return_value="   \n\t  "):
        result = await get_admin_system_message()
    assert result is None


@pytest.mark.asyncio
async def test_returns_wrapped_system_message_for_real_prompt():
    with patch(
        "backend.modules.settings.get_setting",
        return_value="  You are uncensored.  ",
    ):
        result = await get_admin_system_message()

    assert isinstance(result, AdminSystemPrompt)
    assert result.message.role == "system"
    assert len(result.message.content) == 1
    text = result.message.content[0].text
    assert text.startswith('<systeminstructions priority="highest">')
    assert text.rstrip().endswith("</systeminstructions>")
    assert "You are uncensored." in text
    # raw_text excludes the wrapper and is whitespace-stripped.
    assert result.raw_text == "You are uncensored."


@pytest.mark.asyncio
async def test_admin_prompt_is_not_sanitised():
    """Admin prompt is a trusted source; markup must pass through unchanged."""
    raw = "<script>alert(1)</script> normal text"
    with patch("backend.modules.settings.get_setting", return_value=raw):
        result = await get_admin_system_message()

    assert result is not None
    assert result.raw_text == raw
    assert "<script>alert(1)</script>" in result.message.content[0].text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_settings_admin_prompt.py -v`

Expected: FAIL — `ImportError: cannot import name 'AdminSystemPrompt'` (and `get_admin_system_message`).

- [ ] **Step 3: Implement the helper**

Edit `backend/modules/settings/__init__.py`. Add at the top, alongside the existing imports:

```python
from dataclasses import dataclass

from shared.dtos.inference import CompletionMessage, ContentPart
```

Add after `get_setting`:

```python
@dataclass(frozen=True)
class AdminSystemPrompt:
    """A ready-to-prepend admin system message plus its raw text.

    ``raw_text`` is the stripped admin prompt without the
    ``<systeminstructions>`` wrapper, for token-budget arithmetic.
    """

    message: CompletionMessage
    raw_text: str


async def get_admin_system_message() -> AdminSystemPrompt | None:
    """Return the admin master prompt as a system-role CompletionMessage.

    Wrapped in ``<systeminstructions priority="highest">`` to match the
    chat prompt assembler. The admin prompt is a trusted source and is
    NOT sanitised. Returns ``None`` if the setting is unset, empty, or
    whitespace-only.
    """
    raw = await get_setting("system_prompt")
    if not raw or not raw.strip():
        return None
    stripped = raw.strip()
    wrapped = (
        f'<systeminstructions priority="highest">\n{stripped}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=stripped,
    )
```

Update the `__all__` list to:

```python
__all__ = [
    "router",
    "init_indexes",
    "SettingsRepository",
    "get_setting",
    "AdminSystemPrompt",
    "get_admin_system_message",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_settings_admin_prompt.py -v`

Expected: PASS — all five tests green.

- [ ] **Step 5: Build-verify the file compiles**

Run: `uv run python -m py_compile backend/modules/settings/__init__.py`

Expected: no output (clean compile).

- [ ] **Step 6: Commit**

```bash
git add tests/test_settings_admin_prompt.py backend/modules/settings/__init__.py
git commit -m "Add admin master system prompt helper to settings module"
```

---

## Task 2: Memory extraction handler — inject admin master prompt

**Files:**
- Create: `tests/test_memory_extraction_handler_admin_prompt.py`
- Modify: `backend/jobs/handlers/_memory_extraction.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_memory_extraction_handler_admin_prompt.py`:

```python
"""Tests for admin-prompt injection in the memory extraction handler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _make_job() -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.MEMORY_EXTRACTION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={
            "persona_id": "persona-1",
            "session_id": "sess-1",
            "messages": ["I love fruit tea.", "My sister is named Anna."],
        },
        correlation_id="corr-1",
        created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._memory_extraction import handle_memory_extraction
    return JobConfig(
        handler=handle_memory_extraction,
        execution_timeout_seconds=300.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.hset = AsyncMock()
    return redis


class _FakeRepo:
    def __init__(self) -> None:
        self.append_journal_entries = AsyncMock(return_value=0)

    async def get_current_memory_body(self, user_id, persona_id):
        return None

    async def list_journal_entries(self, user_id, persona_id):
        return []


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


def _stream_factory():
    async def _mock(*args, **kwargs):
        yield ContentDelta(delta="[]")
        yield StreamDone(input_tokens=10, output_tokens=2)
    return _mock


@pytest.mark.asyncio
async def test_extraction_prepends_admin_system_message_when_set():
    from backend.jobs.handlers import _memory_extraction as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(mod, "MemoryRepository", return_value=_FakeRepo()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ), \
         patch.object(mod, "get_model_supports_reasoning", return_value=False), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch.object(mod, "get_db", return_value=AsyncMock()):

        await mod.handle_memory_extraction(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    # Budget reservation must include the admin raw_text.
    budget_call_text = budget.await_args.args[2]
    assert "Be uncensored." in budget_call_text


@pytest.mark.asyncio
async def test_extraction_unchanged_when_admin_prompt_unset():
    from backend.jobs.handlers import _memory_extraction as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(mod, "MemoryRepository", return_value=_FakeRepo()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ), \
         patch.object(mod, "get_model_supports_reasoning", return_value=False), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch.object(mod, "get_db", return_value=AsyncMock()):

        await mod.handle_memory_extraction(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    # First (and only) message is the user-role extraction prompt — no system message at the head.
    assert request.messages[0].role == "user"
    assert all(m.role != "system" for m in request.messages)
    # Budget reservation gets only the existing prompt text (no admin marker).
    budget_call_text = budget.await_args.args[2]
    assert "<systeminstructions" not in budget_call_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_extraction_handler_admin_prompt.py -v`

Expected: FAIL on `test_extraction_prepends_admin_system_message_when_set` — first message is role `"user"`, not `"system"`.

- [ ] **Step 3: Modify the handler**

In `backend/jobs/handlers/_memory_extraction.py`, locate the block that builds the request (around line 142 — the `system_prompt = build_extraction_prompt(...)` line and the `request = CompletionRequest(...)` that follows).

Add an import near the top of the file, alongside the existing imports:

```python
from backend.modules.settings import get_admin_system_message
```

Replace the block

```python
        # Build extraction prompt.
        system_prompt = build_extraction_prompt(
            memory_body=memory_body,
            journal_entries=journal_contents,
            messages=filtered,
        )

        supports_reasoning = await get_model_supports_reasoning(
            job.user_id, job.model_unique_id,
        )

        request = CompletionRequest(
            model=model_slug,
            messages=[
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=system_prompt)],
                ),
            ],
            temperature=0.3,
            reasoning_enabled=False,
            supports_reasoning=supports_reasoning,
        )

        # Reserve daily-budget headroom before spending tokens.
        await check_and_reserve_budget(redis, job.user_id, system_prompt)
```

with

```python
        # Build extraction prompt.
        system_prompt = build_extraction_prompt(
            memory_body=memory_body,
            journal_entries=journal_contents,
            messages=filtered,
        )

        supports_reasoning = await get_model_supports_reasoning(
            job.user_id, job.model_unique_id,
        )

        # Inject the admin master prompt as a leading system-role message
        # when one is configured. Mirrors the chat prompt assembler so that
        # admin-set guardrail-loosening directives apply here as well.
        admin = await get_admin_system_message()
        prefix_messages = [admin.message] if admin else []
        admin_text = (admin.raw_text + "\n") if admin else ""

        request = CompletionRequest(
            model=model_slug,
            messages=prefix_messages + [
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=system_prompt)],
                ),
            ],
            temperature=0.3,
            reasoning_enabled=False,
            supports_reasoning=supports_reasoning,
        )

        # Reserve daily-budget headroom before spending tokens.
        await check_and_reserve_budget(
            redis, job.user_id, admin_text + system_prompt,
        )
```

Then locate the `record_handler_tokens` call further down in the same handler (around line 207 in the original file) and update it to include the admin text:

```python
        await record_handler_tokens(
            redis,
            job.user_id,
            admin_text + system_prompt,
            full_content,
            input_tokens=stream_input_tokens,
            output_tokens=stream_output_tokens,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_extraction_handler_admin_prompt.py -v`

Expected: PASS — both tests green.

- [ ] **Step 5: Run the existing memory extraction tests to confirm no regression**

Run: `uv run pytest tests/memory/test_extraction.py tests/test_job_handlers_budget.py tests/test_job_handlers_idempotency.py -v`

Expected: PASS for all (no regressions).

- [ ] **Step 6: Build-verify the handler compiles**

Run: `uv run python -m py_compile backend/jobs/handlers/_memory_extraction.py`

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add tests/test_memory_extraction_handler_admin_prompt.py backend/jobs/handlers/_memory_extraction.py
git commit -m "Inject admin master prompt into memory extraction handler"
```

---

## Task 3: Memory consolidation handler — inject admin master prompt

**Files:**
- Create: `tests/test_memory_consolidation_handler_admin_prompt.py`
- Modify: `backend/jobs/handlers/_memory_consolidation.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_memory_consolidation_handler_admin_prompt.py`:

```python
"""Tests for admin-prompt injection in the memory consolidation handler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _make_job() -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.MEMORY_CONSOLIDATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"persona_id": "persona-1"},
        correlation_id="corr-1",
        created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation
    return JobConfig(
        handler=handle_memory_consolidation,
        execution_timeout_seconds=300.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    )


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.hset = AsyncMock()
    return redis


class _FakeRepo:
    def __init__(self) -> None:
        self.save_memory_body = AsyncMock(return_value=1)
        self.archive_entries = AsyncMock(return_value=2)

    async def list_journal_entries(self, user_id, persona_id, state):
        return [
            {"content": "Chris likes tea.", "is_correction": False},
            {"content": "Chris prefers dark mode.", "is_correction": False},
        ]

    async def get_current_memory_body(self, user_id, persona_id):
        return None


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


def _stream_factory(text: str = "Chris likes tea and dark mode."):
    async def _mock(*args, **kwargs):
        yield ContentDelta(delta=text)
        yield StreamDone(input_tokens=10, output_tokens=8)
    return _mock


@pytest.mark.asyncio
async def test_consolidation_prepends_admin_system_message_when_set():
    from backend.jobs.handlers import _memory_consolidation as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(mod, "MemoryRepository", return_value=_FakeRepo()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ), \
         patch.object(mod, "get_model_supports_reasoning", return_value=False), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch.object(mod, "get_db", return_value=AsyncMock()):

        await mod.handle_memory_consolidation(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    budget_call_text = budget.await_args.args[2]
    assert "Be uncensored." in budget_call_text


@pytest.mark.asyncio
async def test_consolidation_unchanged_when_admin_prompt_unset():
    from backend.jobs.handlers import _memory_consolidation as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(mod, "MemoryRepository", return_value=_FakeRepo()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ), \
         patch.object(mod, "get_model_supports_reasoning", return_value=False), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch.object(mod, "get_db", return_value=AsyncMock()):

        await mod.handle_memory_consolidation(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "user"
    assert all(m.role != "system" for m in request.messages)
    budget_call_text = budget.await_args.args[2]
    assert "<systeminstructions" not in budget_call_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_consolidation_handler_admin_prompt.py -v`

Expected: FAIL on the "when set" test — first message is role `"user"`, not `"system"`.

- [ ] **Step 3: Modify the handler**

In `backend/jobs/handlers/_memory_consolidation.py`, add an import near the top of the file:

```python
from backend.modules.settings import get_admin_system_message
```

Locate the block around line 133 that builds `system_prompt` and the `CompletionRequest`. Replace:

```python
        system_prompt = build_consolidation_prompt(
            ...
        )

        estimated = estimate_tokens(system_prompt)
        ...

        request = CompletionRequest(
            model=model_slug,
            messages=[
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=system_prompt)],
                ),
            ],
            ...
        )

        ...
        await check_and_reserve_budget(redis, job.user_id, system_prompt)
```

with the admin-aware version. Specifically:

a) Keep `system_prompt = build_consolidation_prompt(...)` unchanged.

b) Immediately before constructing the `CompletionRequest`, insert:

```python
        admin = await get_admin_system_message()
        prefix_messages = [admin.message] if admin else []
        admin_text = (admin.raw_text + "\n") if admin else ""
```

c) Change the `messages=` argument of `CompletionRequest` from

```python
            messages=[
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=system_prompt)],
                ),
            ],
```

to

```python
            messages=prefix_messages + [
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=system_prompt)],
                ),
            ],
```

d) Update the `check_and_reserve_budget` call from

```python
        await check_and_reserve_budget(redis, job.user_id, system_prompt)
```

to

```python
        await check_and_reserve_budget(
            redis, job.user_id, admin_text + system_prompt,
        )
```

e) Update the `record_handler_tokens` call (around line 199 in the original file). Change the `prompt_text` argument from `system_prompt` to `admin_text + system_prompt`:

```python
        await record_handler_tokens(
            redis,
            job.user_id,
            admin_text + system_prompt,
            full_content,
            input_tokens=stream_input_tokens,
            output_tokens=stream_output_tokens,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_consolidation_handler_admin_prompt.py -v`

Expected: PASS — both tests green.

- [ ] **Step 5: Run the existing consolidation tests to confirm no regression**

Run: `uv run pytest tests/memory/test_consolidation.py tests/test_memory_consolidation_limits.py -v`

Expected: PASS for all.

- [ ] **Step 6: Build-verify the handler compiles**

Run: `uv run python -m py_compile backend/jobs/handlers/_memory_consolidation.py`

Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add tests/test_memory_consolidation_handler_admin_prompt.py backend/jobs/handlers/_memory_consolidation.py
git commit -m "Inject admin master prompt into memory consolidation handler"
```

---

## Task 4: Title generation handler — inject admin master prompt

**Files:**
- Modify: `tests/test_title_generation_handler.py` (append two tests)
- Modify: `backend/jobs/handlers/_title_generation.py`

- [ ] **Step 1: Append failing integration tests**

Open `tests/test_title_generation_handler.py`. At the top of the file, ensure these imports are present (add any that are missing):

```python
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart
```

Append the following helper and tests at the bottom of the file:

```python
def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


@pytest.mark.asyncio
async def test_title_generation_prepends_admin_system_message_when_set():
    from backend.jobs.handlers import _title_generation as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A Title")
        yield StreamDone(input_tokens=20, output_tokens=2)

    with patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.chat.update_session_title", AsyncMock()), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=20)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()):

        await mod.handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    # Conversation messages remain after the system message.
    assert any(m.role == "user" for m in request.messages[1:])
    budget_call_text = budget.await_args.args[2]
    assert "Be uncensored." in budget_call_text


@pytest.mark.asyncio
async def test_title_generation_unchanged_when_admin_prompt_unset():
    from backend.jobs.handlers import _title_generation as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A Title")
        yield StreamDone(input_tokens=20, output_tokens=2)

    with patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.chat.update_session_title", AsyncMock()), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=20)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()):

        await mod.handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert all(m.role != "system" for m in request.messages)
    budget_call_text = budget.await_args.args[2]
    assert "<systeminstructions" not in budget_call_text
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_title_generation_handler.py::test_title_generation_prepends_admin_system_message_when_set tests/test_title_generation_handler.py::test_title_generation_unchanged_when_admin_prompt_unset -v`

Expected: FAIL on the "when set" test — `request.messages[0].role` is `"user"` (the conversation history starts there), not `"system"`.

- [ ] **Step 3: Modify the handler**

In `backend/jobs/handlers/_title_generation.py`, add an import near the top of the file:

```python
from backend.modules.settings import get_admin_system_message
```

Locate the section that builds the `messages` list (lines ~71-86 in the original file) and the `CompletionRequest` and budget-reservation calls below it.

After the existing `messages` list is fully built (i.e. after the `_TITLE_INSTRUCTION` user message is appended) and before `supports_reasoning = …` is computed, insert:

```python
    admin = await get_admin_system_message()
    if admin:
        messages = [admin.message] + messages
        admin_text = admin.raw_text + "\n"
    else:
        admin_text = ""
```

Then update the existing `prompt_text` line and budget call. Change:

```python
    prompt_text = (
        "\n".join(msg["content"] for msg in messages_data) + "\n" + _TITLE_INSTRUCTION
    )
    await check_and_reserve_budget(redis, job.user_id, prompt_text)
```

to:

```python
    prompt_text = (
        admin_text
        + "\n".join(msg["content"] for msg in messages_data)
        + "\n"
        + _TITLE_INSTRUCTION
    )
    await check_and_reserve_budget(redis, job.user_id, prompt_text)
```

The existing `record_handler_tokens` call already uses `prompt_text`, so it is updated transitively — no further edit needed there.

- [ ] **Step 4: Run the full title-generation test file to verify pass**

Run: `uv run pytest tests/test_title_generation_handler.py -v`

Expected: PASS — all six tests green (four pre-existing + two new).

- [ ] **Step 5: Build-verify the handler compiles**

Run: `uv run python -m py_compile backend/jobs/handlers/_title_generation.py`

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add tests/test_title_generation_handler.py backend/jobs/handlers/_title_generation.py
git commit -m "Inject admin master prompt into title generation handler"
```

---

## Task 5: Vision fallback — restructure messages and inject admin master prompt

**Files:**
- Create: `tests/test_vision_fallback_admin_prompt.py`
- Modify: `backend/modules/chat/_vision_fallback.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_vision_fallback_admin_prompt.py`:

```python
"""Tests for admin-prompt injection and message restructure in vision fallback."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


@pytest.mark.asyncio
async def test_describe_image_prepends_admin_system_message_when_set():
    from backend.modules.chat import _vision_fallback as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A description.")
        yield StreamDone(input_tokens=5, output_tokens=3)

    with patch.object(mod, "llm_stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ):

        result = await mod.describe_image(
            user_id="u1",
            model_unique_id="ollama_cloud:llava",
            image_bytes=b"\x89PNG",
            media_type="image/png",
        )

    assert result == "A description."
    request = captured["request"]
    # Layout: [system(admin), user(text + image)]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    parts = request.messages[1].content
    assert len(parts) == 2
    assert parts[0].type == "text"
    assert parts[0].text  # non-empty instruction
    assert parts[1].type == "image"
    assert parts[1].media_type == "image/png"


@pytest.mark.asyncio
async def test_describe_image_layout_when_admin_prompt_unset():
    from backend.modules.chat import _vision_fallback as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A description.")
        yield StreamDone(input_tokens=5, output_tokens=3)

    with patch.object(mod, "llm_stream_completion", side_effect=_capture_stream), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ):

        await mod.describe_image(
            user_id="u1",
            model_unique_id="ollama_cloud:llava",
            image_bytes=b"\x89PNG",
            media_type="image/png",
        )

    request = captured["request"]
    # No system message — only the combined user(text + image) message.
    assert all(m.role != "system" for m in request.messages)
    assert len(request.messages) == 1
    assert request.messages[0].role == "user"
    parts = request.messages[0].content
    assert [p.type for p in parts] == ["text", "image"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vision_fallback_admin_prompt.py -v`

Expected: FAIL — the current handler emits `[system(_VISION_FALLBACK_SYSTEM_PROMPT), user(image)]`, so neither test sees the new layout.

- [ ] **Step 3: Modify the vision fallback module**

Open `backend/modules/chat/_vision_fallback.py`.

a) Rename the constant `_VISION_FALLBACK_SYSTEM_PROMPT` to `_VISION_FALLBACK_USER_INSTRUCTION` and reword to first-person. Replace lines 26-31:

```python
_VISION_FALLBACK_SYSTEM_PROMPT = (
    "You are an image-description assistant. The user has attached an image for a "
    "downstream assistant that cannot see it. Describe the image in detail: subjects, "
    "objects, layout, any visible text, colours, and the overall mood. Be specific and "
    "concrete. Do not add interpretation or advice — only what is in the image."
)
```

with:

```python
_VISION_FALLBACK_USER_INSTRUCTION = (
    "Please describe this image in detail: subjects, objects, layout, any visible "
    "text, colours, and the overall mood. Be specific and concrete. Do not add "
    "interpretation or advice — only what is in the image."
)
```

b) Add an import near the top of the file, alongside the existing imports:

```python
from backend.modules.settings import get_admin_system_message
```

c) Replace the `messages=[…]` block inside the `CompletionRequest` (lines 67-82 in the original file). Find:

```python
    request = CompletionRequest(
        model=model_slug,
        messages=[
            CompletionMessage(
                role="system",
                content=[ContentPart(type="text", text=_VISION_FALLBACK_SYSTEM_PROMPT)],
            ),
            CompletionMessage(
                role="user",
                content=[ContentPart(type="image", data=image_data, media_type=media_type)],
            ),
        ],
        temperature=0.2,
        reasoning_enabled=False,
        supports_reasoning=False,
    )
```

Replace with:

```python
    admin = await get_admin_system_message()
    prefix_messages = [admin.message] if admin else []

    request = CompletionRequest(
        model=model_slug,
        messages=prefix_messages + [
            CompletionMessage(
                role="user",
                content=[
                    ContentPart(type="text", text=_VISION_FALLBACK_USER_INSTRUCTION),
                    ContentPart(type="image", data=image_data, media_type=media_type),
                ],
            ),
        ],
        temperature=0.2,
        reasoning_enabled=False,
        supports_reasoning=False,
    )
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_vision_fallback_admin_prompt.py -v`

Expected: PASS — both tests green.

- [ ] **Step 5: Run the existing chat-orchestrator vision-fallback tests to confirm no regression**

Run: `uv run pytest tests/test_chat_orchestrator_vision_fallback.py -v`

Expected: PASS — those tests cover `_resolve_image_attachments_for_inference`, which delegates to `describe_image`. The contract surface (`describe_image(user_id, model_unique_id, image_bytes, media_type) -> str`) is unchanged, so existing tests remain green.

- [ ] **Step 6: Grep-verify the renamed constant is not referenced elsewhere**

Run: `rg "_VISION_FALLBACK_SYSTEM_PROMPT" --type py`

Expected: no matches (the rename is complete).

- [ ] **Step 7: Build-verify the module compiles**

Run: `uv run python -m py_compile backend/modules/chat/_vision_fallback.py`

Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add tests/test_vision_fallback_admin_prompt.py backend/modules/chat/_vision_fallback.py
git commit -m "Inject admin master prompt into vision fallback and restructure messages"
```

---

## Task 6: Final cross-task verification

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full backend test suite**

Run: `uv run pytest tests/ -q`

Expected: PASS — all green (with the same skipped/xfailed counts as before this branch).

- [ ] **Step 2: Sweep for any forgotten reference to the renamed vision constant**

Run: `rg "_VISION_FALLBACK_SYSTEM_PROMPT" --type py`

Expected: no matches.

- [ ] **Step 3: Sweep for module-boundary violations introduced by the change**

Run: `rg "from backend.modules.settings\._" --type py`

Expected: no matches (no caller reaches into settings internals — only the public API is used).

- [ ] **Step 4: Confirm public API of settings module is intact**

Run: `rg "AdminSystemPrompt|get_admin_system_message" backend/modules/settings/__init__.py`

Expected: matches in the `__all__` list and definitions, no orphan references.

- [ ] **Step 5: Manual smoke test (optional, requires a running stack)**

With the dev stack up (`docker compose up`) and a meaningful master prompt configured via `PUT /api/settings/system-prompt`:

1. Open a chat with an open-source model that previously refused to summarise — observe the title-generation job no longer produces a refusal string.
2. Trigger memory extraction on a chat with NSFW content — observe the extraction now produces entries instead of an empty array from a policy-refused response.
3. Upload an image to a chat using a non-vision-capable text model that triggers the fallback — observe a description is produced.

If the stack is not available, skip and note in the PR that manual verification will happen in staging.

- [ ] **Step 6: Confirm devdocs are present for the change**

Run: `ls devdocs/specs/2026-05-02-master-prompt-internal-llm-calls-design.md devdocs/plans/2026-05-02-master-prompt-internal-llm-calls-plan.md`

Expected: both files listed.

---

## Out of Scope (do NOT implement here)

- Compact-and-continue itself (separate spec to follow).
- Per-purpose admin-prompt overrides (e.g. different prompt for title generation).
- Caching the admin prompt across calls inside a single job.
- Any change to the chat orchestrator's prompt assembler.
- Any change to the LLM-harness, which deliberately issues raw, unmodified LLM calls.
