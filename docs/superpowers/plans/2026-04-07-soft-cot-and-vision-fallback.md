# Soft Chain-of-Thought & Vision Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two persona-level features: a curated Soft-CoT instruction block with a streaming `<think>` parser for non-reasoning models, and a per-persona vision fallback model that produces image descriptions for non-vision models.

**Architecture:** Both features extend existing structures rather than introducing new modules. Soft-CoT injects a constant text block at the system-prompt-assembly stage and wraps the inference event stream with a small parser that reroutes `<think>…</think>` content from `ContentDelta` to `ThinkingDelta`. Vision fallback replaces the existing "image omitted" placeholder in the orchestrator with a non-streaming completion call against a user-chosen vision model, with retry-once-then-degrade semantics, file-level caching in the storage module, and a per-message snapshot for stable history replay. A new `chat.vision.description` event surfaces the description to the frontend for an expandable per-image block.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + Motor (MongoDB) for backend; Vite + React + TSX + Tailwind for frontend; pytest + Vitest for tests; uv for dependency management.

**Spec reference:** `docs/superpowers/specs/2026-04-07-soft-cot-and-vision-fallback-design.md`

---

## File Structure

### Backend — new files

- `backend/modules/chat/_soft_cot.py` — Soft-CoT instruction text constant + `is_soft_cot_active(...)` helper
- `backend/modules/chat/_soft_cot_parser.py` — `wrap_with_soft_cot_parser(stream)` async generator
- `backend/modules/chat/_vision_fallback.py` — `describe_image(...)` runner with retry-once

### Backend — modified files

- `shared/topics.py` — add `CHAT_VISION_DESCRIPTION`
- `shared/events/chat.py` — add `ChatVisionDescriptionEvent`
- `shared/dtos/persona.py` — add `soft_cot_enabled` and `vision_fallback_model` to all persona DTOs
- `shared/dtos/chat.py` — add `VisionDescriptionSnapshotDto` and field on `ChatMessageDto`
- `backend/modules/persona/_models.py` — add fields to `PersonaDocument`
- `backend/modules/persona/_repository.py` — persist new fields and surface them in `to_dto`
- `backend/modules/persona/_handlers.py` — pass new fields through create/update routes
- `backend/modules/storage/_models.py` — add `vision_descriptions: dict | None` field
- `backend/modules/storage/_repository.py` — `get_vision_description`, `store_vision_description`
- `backend/modules/storage/__init__.py` — expose new public functions
- `backend/modules/chat/_models.py` — add `vision_descriptions_used` field
- `backend/modules/chat/_repository.py` — persist and read `vision_descriptions_used`
- `backend/modules/chat/_prompt_assembler.py` — append Soft-CoT block when active; signature change
- `backend/modules/chat/_inference.py` — accept optional `wrap_stream_fn`
- `backend/modules/chat/_orchestrator.py` — vision fallback path + Soft-CoT wrapping + snapshot read for history replay
- `backend/modules/chat/_handlers_ws.py` — apply Soft-CoT wrapping in the secondary inference path

### Backend — new tests

- `tests/test_soft_cot_parser.py`
- `tests/test_soft_cot_prompt_assembly.py`
- `tests/test_storage_vision_cache.py`
- `tests/test_chat_orchestrator_vision_fallback.py`
- `tests/llm_scenarios/soft_cot_mistral.json`
- `tests/llm_scenarios/vision_fallback_mistral.json`

### Frontend — modified files

- `frontend/src/core/types/persona.ts` — add fields to `PersonaDto` and request types
- `frontend/src/core/api/chat.ts` — add `vision_descriptions_used` to `ChatMessageDto`
- `frontend/src/core/types/events.ts` — add `CHAT_VISION_DESCRIPTION` topic
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — toggle + dropdown
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — extend `DEFAULT_PERSONA`
- `frontend/src/core/store/chatStore.ts` — vision description map keyed by `(correlation_id, file_id)`
- `frontend/src/features/chat/useChatStream.ts` — subscribe to new event
- `frontend/src/features/chat/UserBubble.tsx` — render `VisionDescriptionBlock` per image attachment

### Frontend — new files

- `frontend/src/features/chat/VisionDescriptionBlock.tsx`
- `frontend/src/features/chat/__tests__/VisionDescriptionBlock.test.tsx`

---

## Phase 1 — Shared contracts

### Task 1: Add `CHAT_VISION_DESCRIPTION` topic constant

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Add the constant**

In `shared/topics.py`, in the "Chat inference" section (just after `CHAT_STREAM_ERROR`), add:

```python
    CHAT_VISION_DESCRIPTION = "chat.vision.description"
```

- [ ] **Step 2: Verify file compiles**

Run: `uv run python -m py_compile shared/topics.py`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add shared/topics.py
git commit -m "Add chat.vision.description topic constant"
```

---

### Task 2: Add `ChatVisionDescriptionEvent`

**Files:**
- Modify: `shared/events/chat.py`

- [ ] **Step 1: Add the event class**

At the end of `shared/events/chat.py`, append:

```python
class ChatVisionDescriptionEvent(BaseModel):
    type: str = "chat.vision.description"
    correlation_id: str
    file_id: str
    display_name: str
    model_id: str
    status: Literal["pending", "success", "error"]
    text: str | None = None
    error: str | None = None
    timestamp: datetime
```

- [ ] **Step 2: Verify file compiles**

Run: `uv run python -m py_compile shared/events/chat.py`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add shared/events/chat.py
git commit -m "Add ChatVisionDescriptionEvent"
```

---

### Task 3: Extend persona DTOs with new optional fields

**Files:**
- Modify: `shared/dtos/persona.py`

- [ ] **Step 1: Add fields to `PersonaDto`**

In the `PersonaDto` class, after the `reasoning_enabled: bool` line, add:

```python
    soft_cot_enabled: bool = False
    vision_fallback_model: str | None = None
```

- [ ] **Step 2: Add fields to `CreatePersonaDto`**

In the `CreatePersonaDto` class, after `reasoning_enabled: bool = False`, add:

```python
    soft_cot_enabled: bool = False
    vision_fallback_model: str | None = None
```

- [ ] **Step 3: Add fields to `UpdatePersonaDto`**

In the `UpdatePersonaDto` class, after `reasoning_enabled: bool | None = None`, add:

```python
    soft_cot_enabled: bool | None = None
    vision_fallback_model: str | None = None
```

- [ ] **Step 4: Verify file compiles**

Run: `uv run python -m py_compile shared/dtos/persona.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/persona.py
git commit -m "Add soft_cot_enabled and vision_fallback_model to persona DTOs"
```

---

### Task 4: Add `VisionDescriptionSnapshotDto` and extend `ChatMessageDto`

**Files:**
- Modify: `shared/dtos/chat.py`

- [ ] **Step 1: Read the current file**

Run: `cat shared/dtos/chat.py`
Note where `ChatMessageDto` is defined and which fields it currently has. The new field will be added at the end of `ChatMessageDto`.

- [ ] **Step 2: Add the snapshot DTO and extend the message DTO**

Add the new class near the top of the file (before `ChatMessageDto`):

```python
class VisionDescriptionSnapshotDto(BaseModel):
    file_id: str
    display_name: str
    model_id: str
    text: str
```

In `ChatMessageDto`, add this field at the end of the field list:

```python
    vision_descriptions_used: list[VisionDescriptionSnapshotDto] | None = None
```

If `BaseModel` is not yet imported in this file, add `from pydantic import BaseModel` at the top.

- [ ] **Step 3: Verify file compiles**

Run: `uv run python -m py_compile shared/dtos/chat.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/chat.py
git commit -m "Add VisionDescriptionSnapshotDto and field on ChatMessageDto"
```

---

## Phase 2 — Soft-CoT backend

### Task 5: Soft-CoT instruction block + visibility helper

**Files:**
- Create: `backend/modules/chat/_soft_cot.py`

- [ ] **Step 1: Create the file**

```python
"""Soft Chain-of-Thought instruction block and visibility helper.

Internal module — must not be imported from outside ``backend.modules.chat``.

The instruction text is intentionally a single curated block covering both
analytical step-by-step reasoning and relational/empathic reasoning. It is
maintained centrally in Phase 1; per-persona overrides are out of scope.
"""

# Stable marker substring used by tests to assert the block was injected
# without coupling them to the full prose. Do not change without updating
# the test assertions.
SOFT_COT_MARKER = "<<<SOFT_COT_BLOCK_V1>>>"

SOFT_COT_INSTRUCTIONS = f"""<softcot priority="high">
{SOFT_COT_MARKER}
Before giving your final answer, think step by step and write your reasoning
inside a single <think>...</think> block. Then, on the next line, write the
final answer for the user. Do not put the final answer inside <think>.

Apply this to two complementary modes of reasoning:

1. Analytical reasoning — for technical, factual, or hard-science questions:
   enumerate your assumptions, work through them in order, double-check before
   you commit to a conclusion. Show the work, do not skip steps.

2. Relational reasoning — for psychology, emotion, subtext, mood, and
   interpretation: read between the lines, name the emotional state you
   suspect, and be willing to make associative leaps and bold interpretations
   rather than hedging. Empathy is itself a step-by-step process: notice,
   name, connect, respond.

If the user's question only needs one of these modes, use that one. If both
apply, use both. The thinking block can be as short or as long as the
question demands.
</softcot>"""


def is_soft_cot_active(
    soft_cot_enabled: bool,
    supports_reasoning: bool,
    reasoning_enabled: bool,
) -> bool:
    """Decide whether the Soft-CoT block should be injected for an inference call.

    Active if:
      - the user has opted in via the persona toggle, AND
      - either the model has no native reasoning capability,
        or the model has it but the user has turned Hard-CoT off for this call.

    The persona's ``soft_cot_enabled`` flag is never silently mutated by this
    helper; visibility is recomputed at every inference call.
    """
    if not soft_cot_enabled:
        return False
    if not supports_reasoning:
        return True
    return not reasoning_enabled
```

- [ ] **Step 2: Verify file compiles**

Run: `uv run python -m py_compile backend/modules/chat/_soft_cot.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_soft_cot.py
git commit -m "Add Soft-CoT instruction block and visibility helper"
```

---

### Task 6: Soft-CoT visibility helper unit tests

**Files:**
- Create: `tests/test_soft_cot_visibility.py`

- [ ] **Step 1: Write the failing tests**

```python
from backend.modules.chat._soft_cot import is_soft_cot_active, SOFT_COT_MARKER, SOFT_COT_INSTRUCTIONS


def test_inactive_when_soft_cot_disabled():
    assert is_soft_cot_active(False, supports_reasoning=False, reasoning_enabled=False) is False
    assert is_soft_cot_active(False, supports_reasoning=True, reasoning_enabled=False) is False
    assert is_soft_cot_active(False, supports_reasoning=True, reasoning_enabled=True) is False


def test_active_when_non_reasoning_model():
    assert is_soft_cot_active(True, supports_reasoning=False, reasoning_enabled=False) is True
    # reasoning_enabled is moot when the model can't reason
    assert is_soft_cot_active(True, supports_reasoning=False, reasoning_enabled=True) is True


def test_inactive_when_hard_cot_takes_over():
    assert is_soft_cot_active(True, supports_reasoning=True, reasoning_enabled=True) is False


def test_active_when_reasoning_capable_but_hard_cot_off():
    assert is_soft_cot_active(True, supports_reasoning=True, reasoning_enabled=False) is True


def test_marker_is_present_in_block():
    assert SOFT_COT_MARKER in SOFT_COT_INSTRUCTIONS
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_soft_cot_visibility.py -v`
Expected: 5 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_soft_cot_visibility.py
git commit -m "Test Soft-CoT visibility helper"
```

---

### Task 7: SoftCotStreamParser — failing tests for the streaming `<think>` parser

**Files:**
- Create: `tests/test_soft_cot_parser.py`

The parser will be an async generator that wraps an upstream `AsyncIterator[ProviderStreamEvent]` and yields the same events with one transformation: `ContentDelta` content inside `<think>...</think>` becomes `ThinkingDelta`. Tag detection must survive splits across chunk boundaries. Other event types (`ToolCallEvent`, `StreamDone`, `StreamError`) pass through unchanged.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from backend.modules.llm import ContentDelta, StreamDone, StreamError, ThinkingDelta, ToolCallEvent
from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser


async def _collect(gen):
    out = []
    async for ev in gen:
        out.append(ev)
    return out


async def _stream(*events):
    for ev in events:
        yield ev


@pytest.mark.asyncio
async def test_passthrough_when_no_tags():
    src = _stream(
        ContentDelta(delta="hello "),
        ContentDelta(delta="world"),
        StreamDone(input_tokens=1, output_tokens=2),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    assert [type(e).__name__ for e in out] == ["ContentDelta", "ContentDelta", "StreamDone"]
    assert out[0].delta == "hello "
    assert out[1].delta == "world"


@pytest.mark.asyncio
async def test_whole_think_block_in_one_chunk():
    src = _stream(
        ContentDelta(delta="<think>reasoning here</think>final"),
        StreamDone(input_tokens=1, output_tokens=2),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    types = [type(e).__name__ for e in out]
    assert "ThinkingDelta" in types
    assert "ContentDelta" in types
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    assert thinking == "reasoning here"
    assert content == "final"


@pytest.mark.asyncio
async def test_tag_split_across_chunks():
    src = _stream(
        ContentDelta(delta="<thi"),
        ContentDelta(delta="nk>hello"),
        ContentDelta(delta="</thi"),
        ContentDelta(delta="nk>world"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    assert thinking == "hello"
    assert content == "world"


@pytest.mark.asyncio
async def test_multiple_think_blocks():
    src = _stream(
        ContentDelta(delta="<think>first</think>between<think>second</think>after"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    assert thinking == "firstsecond"
    assert content == "betweenafter"


@pytest.mark.asyncio
async def test_lookalike_tag_passes_through():
    src = _stream(
        ContentDelta(delta="<thirsty> dragon </thirsty> not a think tag"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    content = "".join(e.delta for e in out if isinstance(e, ContentDelta))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    assert "thirsty" in content
    assert thinking == ""


@pytest.mark.asyncio
async def test_unclosed_think_flushed_on_done():
    src = _stream(
        ContentDelta(delta="<think>I never finish"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    thinking = "".join(e.delta for e in out if isinstance(e, ThinkingDelta))
    assert thinking == "I never finish"


@pytest.mark.asyncio
async def test_other_event_types_pass_through():
    src = _stream(
        ContentDelta(delta="before "),
        ToolCallEvent(id="t1", name="x", arguments="{}"),
        ContentDelta(delta="after"),
        StreamError(error_code="boom", message="x"),
        StreamDone(),
    )
    out = await _collect(wrap_with_soft_cot_parser(src))
    type_names = [type(e).__name__ for e in out]
    assert "ToolCallEvent" in type_names
    assert "StreamError" in type_names
    assert "StreamDone" in type_names
```

- [ ] **Step 2: Run tests to verify they fail with import error**

Run: `uv run pytest tests/test_soft_cot_parser.py -v`
Expected: ImportError or ModuleNotFoundError for `backend.modules.chat._soft_cot_parser`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_soft_cot_parser.py
git commit -m "Add failing tests for SoftCotStreamParser"
```

---

### Task 8: Implement `wrap_with_soft_cot_parser`

**Files:**
- Create: `backend/modules/chat/_soft_cot_parser.py`

- [ ] **Step 1: Implement the parser**

```python
"""Streaming `<think>` parser used when Soft-CoT is active.

Internal module — must not be imported from outside ``backend.modules.chat``.

Wraps an async iterator of ``ProviderStreamEvent`` and reroutes any content
that appears inside ``<think>...</think>`` tags from ``ContentDelta`` to
``ThinkingDelta``. The parser is a small state machine that survives tag
splits across chunk boundaries.
"""

from collections.abc import AsyncIterator

from backend.modules.llm import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    ThinkingDelta,
)

_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"
_MAX_LOOKAHEAD = 16  # > len("</think>") with margin for partial matches


async def wrap_with_soft_cot_parser(
    upstream: AsyncIterator[ProviderStreamEvent],
) -> AsyncIterator[ProviderStreamEvent]:
    """Reroute content inside ``<think>...</think>`` to ThinkingDelta events.

    All other event types are passed through unchanged. On stream end, any
    remaining buffered content is flushed in the appropriate channel.
    """
    inside_think = False
    buffer = ""

    async for event in upstream:
        if not isinstance(event, ContentDelta):
            # Flush whatever we have buffered before yielding the foreign event,
            # but only on terminal events to avoid splitting open tag detection.
            if isinstance(event, StreamDone) and buffer:
                if inside_think:
                    yield ThinkingDelta(delta=buffer)
                else:
                    yield ContentDelta(delta=buffer)
                buffer = ""
            yield event
            continue

        buffer += event.delta

        while True:
            if not inside_think:
                idx = buffer.find(_OPEN_TAG)
                if idx >= 0:
                    if idx > 0:
                        yield ContentDelta(delta=buffer[:idx])
                    buffer = buffer[idx + len(_OPEN_TAG):]
                    inside_think = True
                    continue
                # No full open tag found. Emit everything that cannot possibly
                # be the start of a future "<think>" tag.
                safe_emit_until = max(0, len(buffer) - (len(_OPEN_TAG) - 1))
                # Be more conservative: only emit up to a "<" we are not sure about
                safe = buffer[:safe_emit_until]
                tail = buffer[safe_emit_until:]
                # If the tail does not start with '<', it cannot be the start of
                # a tag — emit everything.
                if "<" not in tail:
                    if buffer:
                        yield ContentDelta(delta=buffer)
                    buffer = ""
                else:
                    if safe:
                        yield ContentDelta(delta=safe)
                    # Drop a prefix that cannot be a valid open tag.
                    if len(tail) > _MAX_LOOKAHEAD and not _OPEN_TAG.startswith(tail[: len(_OPEN_TAG)]):
                        yield ContentDelta(delta=tail[:1])
                        buffer = tail[1:]
                        continue
                    buffer = tail
                break
            else:
                idx = buffer.find(_CLOSE_TAG)
                if idx >= 0:
                    if idx > 0:
                        yield ThinkingDelta(delta=buffer[:idx])
                    buffer = buffer[idx + len(_CLOSE_TAG):]
                    inside_think = False
                    continue
                # No close tag yet. Emit everything that cannot be a partial close.
                safe_emit_until = max(0, len(buffer) - (len(_CLOSE_TAG) - 1))
                safe = buffer[:safe_emit_until]
                tail = buffer[safe_emit_until:]
                if "<" not in tail:
                    if buffer:
                        yield ThinkingDelta(delta=buffer)
                    buffer = ""
                else:
                    if safe:
                        yield ThinkingDelta(delta=safe)
                    if len(tail) > _MAX_LOOKAHEAD and not _CLOSE_TAG.startswith(tail[: len(_CLOSE_TAG)]):
                        yield ThinkingDelta(delta=tail[:1])
                        buffer = tail[1:]
                        continue
                    buffer = tail
                break

    # Stream ended without a StreamDone event from upstream — flush.
    if buffer:
        if inside_think:
            yield ThinkingDelta(delta=buffer)
        else:
            yield ContentDelta(delta=buffer)
```

- [ ] **Step 2: Run parser tests to verify they pass**

Run: `uv run pytest tests/test_soft_cot_parser.py -v`
Expected: all 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_soft_cot_parser.py
git commit -m "Implement SoftCotStreamParser"
```

---

### Task 9: PersonaDocument — add new fields

**Files:**
- Modify: `backend/modules/persona/_models.py`

- [ ] **Step 1: Add the fields**

In `PersonaDocument`, after the line `reasoning_enabled: bool`, add:

```python
    soft_cot_enabled: bool = False
    vision_fallback_model: str | None = None
```

- [ ] **Step 2: Verify file compiles**

Run: `uv run python -m py_compile backend/modules/persona/_models.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/persona/_models.py
git commit -m "Add soft_cot_enabled and vision_fallback_model to PersonaDocument"
```

---

### Task 10: PersonaRepository — persist new fields

**Files:**
- Modify: `backend/modules/persona/_repository.py`

- [ ] **Step 1: Extend `create` to write defaults**

In `PersonaRepository.create`, after `"reasoning_enabled": reasoning_enabled,` in the doc dict, add:

```python
            "soft_cot_enabled": False,
            "vision_fallback_model": None,
```

(Defaults are written explicitly so all existing fields remain read-after-write consistent.)

- [ ] **Step 2: Extend `to_dto` to surface the fields**

In `PersonaRepository.to_dto`, after `reasoning_enabled=doc["reasoning_enabled"],`, add:

```python
            soft_cot_enabled=doc.get("soft_cot_enabled", False),
            vision_fallback_model=doc.get("vision_fallback_model"),
```

`.get(...)` is used to remain compatible with persona documents written before this migration.

- [ ] **Step 3: Verify file compiles**

Run: `uv run python -m py_compile backend/modules/persona/_repository.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/persona/_repository.py
git commit -m "Persist and surface soft_cot_enabled and vision_fallback_model in persona repository"
```

---

### Task 11: PersonaHandlers — pass new fields through create route

**Files:**
- Modify: `backend/modules/persona/_handlers.py`

- [ ] **Step 1: Read the relevant section**

The `create_persona` route at lines 70-111 currently passes only the original fields to `repo.create(...)`. The repository's `create` signature does not yet accept the new fields — it sets them to defaults internally. The PATCH route at line 235 already uses `body.model_dump(exclude_none=True)`, so updates to the new fields work for free once the DTOs are extended.

- [ ] **Step 2: Decide on create-time behaviour**

For the create route, the new fields should accept user-provided values from `CreatePersonaDto` (which already has them after Task 3 with default `False` / `None`). To support this, extend `PersonaRepository.create` to accept and write them. Edit `backend/modules/persona/_repository.py`:

In the `create` method signature, after `profile_image: str | None = None,`, add:

```python
        soft_cot_enabled: bool = False,
        vision_fallback_model: str | None = None,
```

In the doc dict written to the collection, replace the two literal lines added in Task 10 with:

```python
            "soft_cot_enabled": soft_cot_enabled,
            "vision_fallback_model": vision_fallback_model,
```

- [ ] **Step 3: Pass the values from the create handler**

In `backend/modules/persona/_handlers.py`, in `create_persona`, in the call to `repo.create(...)`, after `display_order=body.display_order,`, add:

```python
        soft_cot_enabled=body.soft_cot_enabled,
        vision_fallback_model=body.vision_fallback_model,
```

- [ ] **Step 4: Verify both files compile**

Run: `uv run python -m py_compile backend/modules/persona/_repository.py backend/modules/persona/_handlers.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/persona/_repository.py backend/modules/persona/_handlers.py
git commit -m "Wire soft_cot_enabled and vision_fallback_model through persona create route"
```

---

### Task 12: Prompt assembler — failing tests for Soft-CoT injection

**Files:**
- Create: `tests/test_soft_cot_prompt_assembly.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from backend.modules.chat._soft_cot import SOFT_COT_MARKER
from backend.modules.chat._prompt_assembler import assemble


@pytest.mark.asyncio
async def test_block_appended_when_non_reasoning_model_with_soft_cot_on(monkeypatch):
    await _setup_persona(monkeypatch, soft_cot_enabled=True, reasoning_enabled=False)
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_admin_prompt",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_model_instructions",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_user_about_me",
        _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.memory.get_memory_context",
        _async_return(None),
    )

    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=False,
        reasoning_enabled_for_call=False,
    )
    assert SOFT_COT_MARKER in result


@pytest.mark.asyncio
async def test_block_not_appended_when_hard_cot_active(monkeypatch):
    await _setup_persona(monkeypatch, soft_cot_enabled=True, reasoning_enabled=True)
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_admin_prompt", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_model_instructions", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_user_about_me", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.memory.get_memory_context", _async_return(None),
    )

    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=True,
        reasoning_enabled_for_call=True,
    )
    assert SOFT_COT_MARKER not in result


@pytest.mark.asyncio
async def test_block_appended_when_reasoning_capable_but_hard_cot_off(monkeypatch):
    await _setup_persona(monkeypatch, soft_cot_enabled=True, reasoning_enabled=False)
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_admin_prompt", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_model_instructions", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_user_about_me", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.memory.get_memory_context", _async_return(None),
    )

    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=True,
        reasoning_enabled_for_call=False,
    )
    assert SOFT_COT_MARKER in result


@pytest.mark.asyncio
async def test_block_not_appended_when_soft_cot_off(monkeypatch):
    await _setup_persona(monkeypatch, soft_cot_enabled=False, reasoning_enabled=False)
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_admin_prompt", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_model_instructions", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_user_about_me", _async_return(None),
    )
    monkeypatch.setattr(
        "backend.modules.memory.get_memory_context", _async_return(None),
    )

    result = await assemble(
        user_id="u1",
        persona_id="p1",
        model_unique_id="provider:slug",
        supports_reasoning=False,
        reasoning_enabled_for_call=False,
    )
    assert SOFT_COT_MARKER not in result


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


async def _setup_persona(monkeypatch, soft_cot_enabled, reasoning_enabled):
    """Make `_get_persona_prompt` return a stub persona with the given flags."""
    persona_doc = {
        "system_prompt": "you are a helpful assistant",
        "soft_cot_enabled": soft_cot_enabled,
        "reasoning_enabled": reasoning_enabled,
    }

    async def _fake_get_persona_prompt(persona_id, user_id):
        return persona_doc.get("system_prompt")

    async def _fake_get_persona(persona_id, user_id):
        return persona_doc

    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_persona_prompt",
        _fake_get_persona_prompt,
    )
    monkeypatch.setattr(
        "backend.modules.chat._prompt_assembler._get_persona_doc",
        _fake_get_persona,
    )
```

Note: this test references a helper `_get_persona_doc` which we will introduce in Task 13 alongside the assembler change. Tests fail on import until then.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_soft_cot_prompt_assembly.py -v`
Expected: tests fail with `TypeError` (extra kwargs to `assemble`) or `AttributeError` for `_get_persona_doc`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_soft_cot_prompt_assembly.py
git commit -m "Add failing tests for Soft-CoT prompt assembly"
```

---

### Task 13: Prompt assembler — inject Soft-CoT block when active

**Files:**
- Modify: `backend/modules/chat/_prompt_assembler.py`

- [ ] **Step 1: Add the persona-doc helper**

After the existing `_get_persona_prompt` function, add:

```python
async def _get_persona_doc(persona_id: str | None, user_id: str) -> dict | None:
    """Fetch the full persona document (used for soft_cot_enabled lookup)."""
    if not persona_id:
        return None
    from backend.modules.persona import get_persona
    return await get_persona(persona_id, user_id)
```

- [ ] **Step 2: Extend the `assemble` signature and logic**

Replace the existing `assemble` function with:

```python
async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
    supports_reasoning: bool = False,
    reasoning_enabled_for_call: bool = False,
) -> str:
    """Assemble the full XML system prompt for LLM consumption.

    ``supports_reasoning`` and ``reasoning_enabled_for_call`` are used to
    decide whether to inject the Soft-CoT instruction block. They default to
    False so that legacy callers (preview, scripts) get the legacy behaviour.
    """
    from backend.modules.chat._soft_cot import (
        SOFT_COT_INSTRUCTIONS,
        is_soft_cot_active,
    )

    admin_prompt = await _get_admin_prompt()
    model_instructions = await _get_model_instructions(user_id, model_unique_id)
    persona_prompt = await _get_persona_prompt(persona_id, user_id)
    persona_doc = await _get_persona_doc(persona_id, user_id)
    user_about_me = await _get_user_about_me(user_id)

    parts: list[str] = []

    if admin_prompt and admin_prompt.strip():
        parts.append(
            f'<systeminstructions priority="highest">\n{admin_prompt.strip()}\n</systeminstructions>'
        )

    if model_instructions and model_instructions.strip():
        cleaned = sanitise(model_instructions.strip())
        if cleaned:
            parts.append(
                f'<modelinstructions priority="high">\n{cleaned}\n</modelinstructions>'
            )

    if persona_prompt and persona_prompt.strip():
        cleaned = sanitise(persona_prompt.strip())
        if cleaned:
            parts.append(f'<you priority="normal">\n{cleaned}\n</you>')

    # Soft-CoT instruction block — sits between the persona and memory layers
    # so that it is "felt" alongside the persona's voice but does not displace
    # admin or model instructions.
    soft_cot_enabled = bool(persona_doc and persona_doc.get("soft_cot_enabled"))
    if is_soft_cot_active(soft_cot_enabled, supports_reasoning, reasoning_enabled_for_call):
        parts.append(SOFT_COT_INSTRUCTIONS)

    from backend.modules.memory import get_memory_context
    memory_xml = await get_memory_context(user_id, persona_id) if persona_id else None
    if memory_xml:
        parts.append(memory_xml)

    if user_about_me and user_about_me.strip():
        cleaned = sanitise(user_about_me.strip())
        if cleaned:
            parts.append(
                f'<userinfo priority="low">\nWhat the user wants you to know about themselves:\n{cleaned}\n</userinfo>'
            )

    result = "\n\n".join(parts)

    if len(result) > 16000:
        _log.warning(
            "Assembled system prompt is very large (%d chars) for user=%s model=%s — "
            "this may consume a significant portion of the context window",
            len(result), user_id, model_unique_id,
        )

    return result
```

The two new parameters default to `False`, so the preview path and any other caller that does not pass them stays unchanged behaviourally.

- [ ] **Step 3: Run prompt-assembly tests**

Run: `uv run pytest tests/test_soft_cot_prompt_assembly.py -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_prompt_assembler.py
git commit -m "Inject Soft-CoT block during prompt assembly when active"
```

---

### Task 14: Pass Soft-CoT context from orchestrator to prompt assembler

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Read the current call site**

The current `assemble(...)` call is at lines 96-100 of `_orchestrator.py` and reads:

```python
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
    )
```

This call happens before `supports_reasoning` and the resolved `reasoning_enabled` are computed (those are at lines 201-208). We need to compute the reasoning context first, then assemble.

- [ ] **Step 2: Move reasoning resolution above the assemble call**

Just below line 93 (`provider_id, model_slug = model_unique_id.split(":", 1)`), insert:

```python
    # Resolve reasoning context up-front so the prompt assembler can decide
    # whether to inject the Soft-CoT block.
    persona_for_resolve = await get_persona(persona_id, user_id) if persona_id else None
    reasoning_override = session.get("reasoning_override")
    if reasoning_override is not None:
        reasoning_enabled = reasoning_override
    else:
        reasoning_enabled = (
            persona_for_resolve.get("reasoning_enabled", False)
            if persona_for_resolve else False
        )
    supports_reasoning = await get_model_supports_reasoning(provider_id, model_slug)
```

- [ ] **Step 3: Update the `assemble` call**

Replace the `assemble(...)` call (lines 96-100) with:

```python
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
        supports_reasoning=supports_reasoning,
        reasoning_enabled_for_call=reasoning_enabled,
    )
```

- [ ] **Step 4: Remove the now-duplicate resolution block lower in the file**

Delete lines 194-208 (the `# Get persona settings...` block, the `reasoning_override` block, and the `supports_reasoning = await ...` line). They have been moved up.

Replace the `persona = await get_persona(persona_id, user_id) if persona_id else None` line later in the file with `persona = persona_for_resolve` so the rest of the function still has the persona dict available without a second DB call.

- [ ] **Step 5: Verify the file compiles**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Pass reasoning context to prompt assembler from orchestrator"
```

---

### Task 15: Wire Soft-CoT parser into inference runner

**Files:**
- Modify: `backend/modules/chat/_inference.py`
- Modify: `backend/modules/chat/_orchestrator.py`
- Modify: `backend/modules/chat/_handlers_ws.py`

The cleanest place to wrap the upstream stream is at the `stream_fn` callback level, because both the orchestrator and the WS handlers create their own `stream_fn` and that closure is the natural place to apply policies.

- [ ] **Step 1: Wrap the stream in `_orchestrator.py`**

Find the `stream_fn` defined inside `run_inference` (around line 241):

```python
    def stream_fn(extra_messages=None):
        req = request
        if extra_messages:
            extended = list(request.messages) + extra_messages
            req = request.model_copy(update={"messages": extended})
        return llm_stream_completion(user_id, provider_id, req)
```

Replace it with:

```python
    from backend.modules.chat._soft_cot import is_soft_cot_active
    from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser

    soft_cot_on = is_soft_cot_active(
        soft_cot_enabled=bool(persona_for_resolve and persona_for_resolve.get("soft_cot_enabled")),
        supports_reasoning=supports_reasoning,
        reasoning_enabled=reasoning_enabled,
    )

    def stream_fn(extra_messages=None):
        req = request
        if extra_messages:
            extended = list(request.messages) + extra_messages
            req = request.model_copy(update={"messages": extended})
        upstream = llm_stream_completion(user_id, provider_id, req)
        if soft_cot_on:
            return wrap_with_soft_cot_parser(upstream)
        return upstream
```

- [ ] **Step 2: Mirror the wrapping in `_handlers_ws.py`**

The secondary inference path lives in `_handlers_ws.py` around lines 280-365. Apply the same pattern: compute `soft_cot_on` after the persona and capabilities are loaded, and wrap inside `stream_fn`. Insert just above the `def stream_fn(extra_messages=None):` block:

```python
        from backend.modules.chat._soft_cot import is_soft_cot_active
        from backend.modules.chat._soft_cot_parser import wrap_with_soft_cot_parser

        soft_cot_on = is_soft_cot_active(
            soft_cot_enabled=bool(persona.get("soft_cot_enabled")),
            supports_reasoning=supports_reasoning,
            reasoning_enabled=persona.get("reasoning_enabled", False),
        )
```

Then change the existing `stream_fn` to wrap the upstream when `soft_cot_on` is true (same shape as in step 1).

Also, in this handler the `assemble(...)` call at lines 294-298 currently does not pass the new kwargs. Update it to pass `supports_reasoning=supports_reasoning, reasoning_enabled_for_call=persona.get("reasoning_enabled", False)`. Note that `supports_reasoning` is computed at line 315 — move that line above the `assemble` call.

- [ ] **Step 3: Verify both files compile**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py backend/modules/chat/_handlers_ws.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/chat/_handlers_ws.py
git commit -m "Wire SoftCotStreamParser into inference paths"
```

---

## Phase 3 — Vision fallback backend

### Task 16: Storage cache — failing tests

**Files:**
- Create: `tests/test_storage_vision_cache.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from backend.modules.storage._repository import StorageRepository


@pytest.mark.asyncio
async def test_store_then_get_returns_text(in_memory_db):
    repo = StorageRepository(in_memory_db)
    await repo._col.insert_one({
        "_id": "f1", "user_id": "u1", "original_name": "x.png",
        "display_name": "x.png", "media_type": "image/png", "size_bytes": 1,
        "file_path": "u1/f1.bin", "created_at": _now(), "updated_at": _now(),
    })
    await repo.store_vision_description("f1", "u1", "ollama_cloud:mistral", "a flower")
    got = await repo.get_vision_description("f1", "u1", "ollama_cloud:mistral")
    assert got == "a flower"


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(in_memory_db):
    repo = StorageRepository(in_memory_db)
    await repo._col.insert_one({
        "_id": "f1", "user_id": "u1", "original_name": "x.png",
        "display_name": "x.png", "media_type": "image/png", "size_bytes": 1,
        "file_path": "u1/f1.bin", "created_at": _now(), "updated_at": _now(),
    })
    got = await repo.get_vision_description("f1", "u1", "ollama_cloud:mistral")
    assert got is None


@pytest.mark.asyncio
async def test_two_models_coexist(in_memory_db):
    repo = StorageRepository(in_memory_db)
    await repo._col.insert_one({
        "_id": "f1", "user_id": "u1", "original_name": "x.png",
        "display_name": "x.png", "media_type": "image/png", "size_bytes": 1,
        "file_path": "u1/f1.bin", "created_at": _now(), "updated_at": _now(),
    })
    await repo.store_vision_description("f1", "u1", "ollama_cloud:mistral", "mistral text")
    await repo.store_vision_description("f1", "u1", "ollama_cloud:glm", "glm text")
    assert await repo.get_vision_description("f1", "u1", "ollama_cloud:mistral") == "mistral text"
    assert await repo.get_vision_description("f1", "u1", "ollama_cloud:glm") == "glm text"


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
```

`in_memory_db` is the existing pytest fixture used throughout the project's tests. If it does not exist, look for the fixture pattern used by an existing repository test file (e.g. `tests/test_chat_repository.py`) and reuse that exact fixture import and signature.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage_vision_cache.py -v`
Expected: AttributeError or test failures because `get_vision_description` and `store_vision_description` do not exist.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_storage_vision_cache.py
git commit -m "Add failing tests for storage vision description cache"
```

---

### Task 17: Storage repository — implement cache methods

**Files:**
- Modify: `backend/modules/storage/_repository.py`
- Modify: `backend/modules/storage/_models.py`
- Modify: `backend/modules/storage/__init__.py`

- [ ] **Step 1: Add field to the document model**

In `backend/modules/storage/_models.py`, in `StorageFileDocument`, after `text_preview: str | None = None`, add:

```python
    vision_descriptions: dict[str, dict] | None = None
```

The dict shape per entry is `{"text": str, "model_id": str, "created_at": datetime}`. We use a plain dict instead of a nested model because Mongo round-tripping is simpler and this field is internal to the storage module.

- [ ] **Step 2: Add repository methods**

In `backend/modules/storage/_repository.py`, after the `find_by_ids` method, add:

```python
    async def get_vision_description(
        self, file_id: str, user_id: str, model_id: str,
    ) -> str | None:
        """Return cached vision description text for a (file, model) pair."""
        doc = await self._col.find_one(
            {"_id": file_id, "user_id": user_id},
            {f"vision_descriptions.{model_id}": 1},
        )
        if not doc:
            return None
        entry = (doc.get("vision_descriptions") or {}).get(model_id)
        if not entry:
            return None
        return entry.get("text")

    async def store_vision_description(
        self, file_id: str, user_id: str, model_id: str, text: str,
    ) -> None:
        """Persist a vision description for a (file, model) pair."""
        await self._col.update_one(
            {"_id": file_id, "user_id": user_id},
            {"$set": {
                f"vision_descriptions.{model_id}": {
                    "text": text,
                    "model_id": model_id,
                    "created_at": datetime.now(timezone.utc),
                }
            }},
        )
```

- [ ] **Step 3: Expose them as cross-module API**

In `backend/modules/storage/__init__.py`, after `get_files_by_ids`, add:

```python
async def get_cached_vision_description(
    file_id: str, user_id: str, model_id: str,
) -> str | None:
    """Cross-module API: read a cached vision description, or None if missing."""
    db = get_db()
    repo = StorageRepository(db)
    return await repo.get_vision_description(file_id, user_id, model_id)


async def store_vision_description(
    file_id: str, user_id: str, model_id: str, text: str,
) -> None:
    """Cross-module API: persist a vision description for a (file, model) pair."""
    db = get_db()
    repo = StorageRepository(db)
    await repo.store_vision_description(file_id, user_id, model_id, text)
```

Add both names to `__all__`:

```python
__all__ = [
    "router",
    "init_indexes",
    "get_file_metadata",
    "get_files_by_ids",
    "get_cached_vision_description",
    "store_vision_description",
]
```

- [ ] **Step 4: Run cache tests**

Run: `uv run pytest tests/test_storage_vision_cache.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/storage/_models.py backend/modules/storage/_repository.py backend/modules/storage/__init__.py
git commit -m "Add vision description cache to storage module"
```

---

### Task 18: ChatMessageDocument — add vision snapshot field

**Files:**
- Modify: `backend/modules/chat/_models.py`

- [ ] **Step 1: Add the field**

In `ChatMessageDocument`, after `thinking: str | None = None`, add:

```python
    vision_descriptions_used: list[dict] | None = None
```

- [ ] **Step 2: Verify file compiles**

Run: `uv run python -m py_compile backend/modules/chat/_models.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_models.py
git commit -m "Add vision_descriptions_used field to ChatMessageDocument"
```

---

### Task 19: ChatRepository — persist and read vision snapshots

**Files:**
- Modify: `backend/modules/chat/_repository.py`

- [ ] **Step 1: Extend `save_message` signature**

In `ChatRepository.save_message`, add a new keyword argument at the end of the parameter list:

```python
        vision_descriptions_used: list[dict] | None = None,
```

In the body, after the `if attachment_refs:` block, add:

```python
        if vision_descriptions_used:
            doc["vision_descriptions_used"] = vision_descriptions_used
```

- [ ] **Step 2: Surface the field in `to_dto`**

Locate the function that converts a message doc to its DTO (around line 445-470 — search for `attachments=attachments`). After the `attachments=attachments,` line, add:

```python
            vision_descriptions_used=[
                {
                    "file_id": s["file_id"],
                    "display_name": s["display_name"],
                    "model_id": s["model_id"],
                    "text": s["text"],
                }
                for s in (doc.get("vision_descriptions_used") or [])
            ] or None,
        )
```

(Adjust the closing parenthesis position to match the surrounding return-tuple shape.)

- [ ] **Step 3: Verify file compiles**

Run: `uv run python -m py_compile backend/modules/chat/_repository.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_repository.py
git commit -m "Persist and read vision_descriptions_used in chat repository"
```

---

### Task 20: Vision fallback runner — failing tests

**Files:**
- Create: `tests/test_vision_fallback_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from backend.modules.chat._vision_fallback import describe_image, VisionFallbackError


class _FakeAdapter:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    async def stream_completion(self, api_key, request):
        self.calls += 1
        action = self.behaviour(self.calls)
        if isinstance(action, Exception):
            raise action
        for ev in action:
            yield ev


@pytest.mark.asyncio
async def test_success_first_try(monkeypatch):
    from backend.modules.llm import ContentDelta, StreamDone

    def behaviour(call_no):
        return [ContentDelta(delta="a flower"), StreamDone()]

    fake = _FakeAdapter(behaviour)
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_adapter_for",
        lambda mid: fake,
    )
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_api_key_for",
        _async_return("k"),
    )

    text = await describe_image("u1", "ollama_cloud:mistral", b"\x89PNG", "image/png")
    assert text == "a flower"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_retry_once_on_first_failure(monkeypatch):
    from backend.modules.llm import ContentDelta, StreamDone

    def behaviour(call_no):
        if call_no == 1:
            return RuntimeError("cold start")
        return [ContentDelta(delta="success after retry"), StreamDone()]

    fake = _FakeAdapter(behaviour)
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_adapter_for",
        lambda mid: fake,
    )
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_api_key_for",
        _async_return("k"),
    )

    text = await describe_image("u1", "ollama_cloud:mistral", b"\x89PNG", "image/png")
    assert text == "success after retry"
    assert fake.calls == 2


@pytest.mark.asyncio
async def test_raises_after_two_failures(monkeypatch):
    def behaviour(call_no):
        return RuntimeError("still cold")

    fake = _FakeAdapter(behaviour)
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_adapter_for",
        lambda mid: fake,
    )
    monkeypatch.setattr(
        "backend.modules.chat._vision_fallback._get_api_key_for",
        _async_return("k"),
    )

    with pytest.raises(VisionFallbackError):
        await describe_image("u1", "ollama_cloud:mistral", b"\x89PNG", "image/png")
    assert fake.calls == 2


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vision_fallback_runner.py -v`
Expected: ImportError for `backend.modules.chat._vision_fallback`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_vision_fallback_runner.py
git commit -m "Add failing tests for vision fallback runner"
```

---

### Task 21: Implement `describe_image`

**Files:**
- Create: `backend/modules/chat/_vision_fallback.py`

- [ ] **Step 1: Implement the runner**

```python
"""Vision fallback runner — describes an image using a separate vision model.

Internal module — must not be imported from outside ``backend.modules.chat``.

Performs a single non-streaming completion against a user-chosen vision model
and returns the resulting text. Retries exactly once on adapter failure to
absorb cold-start errors at providers like Ollama Cloud.
"""

import base64
import logging

from backend.modules.llm import (
    ADAPTER_REGISTRY,
    PROVIDER_BASE_URLS,
    ContentDelta,
    StreamDone,
    StreamError,
    get_api_key,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

_log = logging.getLogger(__name__)

_VISION_FALLBACK_SYSTEM_PROMPT = (
    "You are an image-description assistant. The user has attached an image "
    "for a downstream assistant that cannot see it. Describe the image in "
    "detail: subjects, objects, layout, any visible text, colours, and the "
    "overall mood. Be specific and concrete. Do not add interpretation or "
    "advice — only what is in the image."
)


class VisionFallbackError(Exception):
    """The vision fallback model failed to produce a description."""


def _get_adapter_for(model_unique_id: str):
    provider_id = model_unique_id.split(":", 1)[0]
    return ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])


async def _get_api_key_for(user_id: str, model_unique_id: str) -> str:
    provider_id = model_unique_id.split(":", 1)[0]
    return await get_api_key(user_id, provider_id)


async def describe_image(
    user_id: str,
    model_unique_id: str,
    image_bytes: bytes,
    media_type: str,
) -> str:
    """Describe an image using the configured vision fallback model.

    Retries once on any exception. Raises VisionFallbackError if both
    attempts fail.
    """
    if ":" not in model_unique_id:
        raise VisionFallbackError(f"Invalid model id: {model_unique_id}")

    _provider_id, model_slug = model_unique_id.split(":", 1)

    request = CompletionRequest(
        model=model_slug,
        messages=[
            CompletionMessage(
                role="system",
                content=[ContentPart(type="text", text=_VISION_FALLBACK_SYSTEM_PROMPT)],
            ),
            CompletionMessage(
                role="user",
                content=[ContentPart(
                    type="image",
                    data=base64.b64encode(image_bytes).decode("ascii"),
                    media_type=media_type,
                )],
            ),
        ],
        temperature=0.2,
        reasoning_enabled=False,
        supports_reasoning=False,
    )

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            text = await _run_once(user_id, model_unique_id, request)
            if text.strip():
                return text.strip()
            last_error = VisionFallbackError("empty response from vision model")
        except Exception as exc:
            _log.warning(
                "vision fallback attempt %d failed for model=%s user=%s: %s",
                attempt, model_unique_id, user_id, exc,
            )
            last_error = exc

    raise VisionFallbackError(
        f"vision fallback failed after retry: {last_error}"
    ) from last_error


async def _run_once(user_id: str, model_unique_id: str, request: CompletionRequest) -> str:
    adapter = _get_adapter_for(model_unique_id)
    api_key = await _get_api_key_for(user_id, model_unique_id)

    parts: list[str] = []
    async for event in adapter.stream_completion(api_key, request):
        if isinstance(event, ContentDelta):
            parts.append(event.delta)
        elif isinstance(event, StreamError):
            raise VisionFallbackError(f"adapter stream error: {event.message}")
        elif isinstance(event, StreamDone):
            break

    return "".join(parts)
```

- [ ] **Step 2: Run runner tests**

Run: `uv run pytest tests/test_vision_fallback_runner.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_vision_fallback.py
git commit -m "Implement vision fallback runner with retry-once"
```

---

### Task 22: Orchestrator — vision fallback path failing tests

**Files:**
- Create: `tests/test_chat_orchestrator_vision_fallback.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the orchestrator's vision fallback integration.

These tests focus on the message-list build phase: given a user message with
image attachments and a non-vision main model, verify that vision fallback
descriptions are produced, cached, snapshotted, and emitted as events.
"""

import pytest

# Import the helper that the orchestrator calls (extracted in Task 23 to make
# the path testable in isolation).
from backend.modules.chat._orchestrator import _resolve_image_attachments_for_inference


@pytest.mark.asyncio
async def test_no_fallback_returns_placeholder_text_part(monkeypatch):
    files = [{
        "_id": "f1", "data": b"\x89PNG", "media_type": "image/png",
        "display_name": "flower.png",
    }]
    parts, snapshots, events_emitted = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=False,
        vision_fallback_model=None,
        emit_event=_capture(events_emitted := []),
        correlation_id="c1",
    )
    assert any("flower.png" in p.text for p in parts if p.type == "text")
    assert snapshots == []
    assert events_emitted == []


@pytest.mark.asyncio
async def test_main_model_supports_vision_uses_image_part(monkeypatch):
    files = [{
        "_id": "f1", "data": b"\x89PNG", "media_type": "image/png",
        "display_name": "flower.png",
    }]
    parts, snapshots, events_emitted = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=True,
        vision_fallback_model="ignored",
        emit_event=_capture(events_emitted := []),
        correlation_id="c1",
    )
    assert any(p.type == "image" for p in parts)
    assert snapshots == []
    assert events_emitted == []


@pytest.mark.asyncio
async def test_cache_hit_skips_describe_call(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return("cached description"),
    )
    called = {"n": 0}
    async def _no_call(*a, **kw):
        called["n"] += 1
        return "should not be called"
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image",
        _no_call,
    )
    files = [{
        "_id": "f1", "data": b"\x89PNG", "media_type": "image/png",
        "display_name": "flower.png",
    }]
    events = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=False,
        vision_fallback_model="ollama_cloud:mistral",
        emit_event=_capture(events),
        correlation_id="c1",
    )
    assert called["n"] == 0
    text_parts = [p.text for p in parts if p.type == "text"]
    assert any("cached description" in t for t in text_parts)
    assert len(snapshots) == 1
    assert snapshots[0]["text"] == "cached description"
    # Cache hit emits a single success event with no pending phase.
    assert len(events) == 1
    assert events[0].status == "success"


@pytest.mark.asyncio
async def test_cache_miss_calls_describe_and_stores(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return(None),
    )
    described = {"n": 0}
    async def _describe(user_id, mid, data, mt):
        described["n"] += 1
        return "fresh description"
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image", _describe,
    )
    stored = {"n": 0}
    async def _store(file_id, user_id, model_id, text):
        stored["n"] += 1
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.store_vision_description", _store,
    )
    files = [{
        "_id": "f1", "data": b"\x89PNG", "media_type": "image/png",
        "display_name": "flower.png",
    }]
    events = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=False,
        vision_fallback_model="ollama_cloud:mistral",
        emit_event=_capture(events),
        correlation_id="c1",
    )
    assert described["n"] == 1
    assert stored["n"] == 1
    assert snapshots[0]["text"] == "fresh description"
    statuses = [e.status for e in events]
    assert statuses == ["pending", "success"]


@pytest.mark.asyncio
async def test_describe_failure_emits_error_event_and_continues(monkeypatch):
    from backend.modules.chat._vision_fallback import VisionFallbackError

    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return(None),
    )
    async def _fail(user_id, mid, data, mt):
        raise VisionFallbackError("boom")
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image", _fail,
    )
    files = [{
        "_id": "f1", "data": b"\x89PNG", "media_type": "image/png",
        "display_name": "flower.png",
    }]
    events = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=False,
        vision_fallback_model="ollama_cloud:mistral",
        emit_event=_capture(events),
        correlation_id="c1",
    )
    text_parts = [p.text for p in parts if p.type == "text"]
    assert any("vision fallback failed" in t.lower() or "image:" in t.lower() for t in text_parts)
    assert snapshots == []
    statuses = [e.status for e in events]
    assert statuses == ["pending", "error"]


@pytest.mark.asyncio
async def test_multiple_images_one_call_per_image(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.get_cached_vision_description",
        _async_return(None),
    )
    seen = []
    async def _describe(user_id, mid, data, mt):
        seen.append(data)
        return f"desc {len(seen)}"
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.describe_image", _describe,
    )
    monkeypatch.setattr(
        "backend.modules.chat._orchestrator.store_vision_description",
        _async_return(None),
    )
    files = [
        {"_id": "f1", "data": b"AAA", "media_type": "image/png", "display_name": "a.png"},
        {"_id": "f2", "data": b"BBB", "media_type": "image/png", "display_name": "b.png"},
    ]
    events = []
    parts, snapshots, _ = await _resolve_image_attachments_for_inference(
        user_id="u1",
        files=files,
        supports_vision=False,
        vision_fallback_model="ollama_cloud:mistral",
        emit_event=_capture(events),
        correlation_id="c1",
    )
    assert len(seen) == 2
    assert len(snapshots) == 2
    assert [s["text"] for s in snapshots] == ["desc 1", "desc 2"]


def _async_return(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def _capture(bucket):
    async def _emit(event):
        bucket.append(event)
    return _emit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_orchestrator_vision_fallback.py -v`
Expected: ImportError for `_resolve_image_attachments_for_inference`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_chat_orchestrator_vision_fallback.py
git commit -m "Add failing tests for orchestrator vision fallback path"
```

---

### Task 23: Orchestrator — extract image-resolution helper and integrate vision fallback

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

The current code at lines 168-191 handles attachment-to-content-part conversion inline. We extract it into a testable helper, add the vision fallback path, and emit events.

- [ ] **Step 1: Add imports at the top of the file**

After the existing `from backend.modules.storage import get_files_by_ids` (which is currently inline at line 170), promote it to the top imports section. Add:

```python
from backend.modules.storage import (
    get_files_by_ids,
    get_cached_vision_description,
    store_vision_description,
)
from backend.modules.chat._vision_fallback import describe_image, VisionFallbackError
from shared.events.chat import ChatVisionDescriptionEvent
```

Remove the inline import on line 170.

- [ ] **Step 2: Add the extracted helper**

Insert this function above `run_inference`:

```python
async def _resolve_image_attachments_for_inference(
    user_id: str,
    files: list[dict],
    supports_vision: bool,
    vision_fallback_model: str | None,
    emit_event,
    correlation_id: str,
) -> tuple[list[ContentPart], list[dict], None]:
    """Convert a list of file dicts into ContentParts plus vision snapshots.

    Returns ``(parts, snapshots, _)`` where:
      - parts: ContentPart list to append to the user message (interleaved
        text/image as appropriate)
      - snapshots: list of vision-description snapshot dicts to persist on
        the saved message document

    For each image attachment:
      1. If the main model supports vision: pass through as an image part.
      2. Else if no fallback configured: emit a placeholder text part.
      3. Else if cache hit: emit a text part from the cache + snapshot +
         success event.
      4. Else: emit pending event, call describe_image, on success store +
         snapshot + success event, on failure emit error event and use a
         placeholder text part.

    Non-image attachments are converted to text parts as in the previous
    inline implementation.
    """
    from datetime import datetime, timezone
    parts: list[ContentPart] = []
    snapshots: list[dict] = []

    for f in files:
        if f.get("data") and f["media_type"].startswith("image/"):
            if supports_vision:
                parts.append(ContentPart(
                    type="image",
                    data=base64.b64encode(f["data"]).decode("ascii"),
                    media_type=f["media_type"],
                ))
                continue

            if not vision_fallback_model:
                parts.append(ContentPart(
                    type="text",
                    text=f"\n[Image: {f['display_name']} — model does not support vision, image omitted]",
                ))
                continue

            cached = await get_cached_vision_description(
                f["_id"], user_id, vision_fallback_model,
            )
            if cached:
                parts.append(ContentPart(
                    type="text",
                    text=f"\n[Image description for {f['display_name']} (via {vision_fallback_model}):\n{cached}\n]",
                ))
                snapshots.append({
                    "file_id": f["_id"],
                    "display_name": f["display_name"],
                    "model_id": vision_fallback_model,
                    "text": cached,
                })
                await emit_event(ChatVisionDescriptionEvent(
                    correlation_id=correlation_id,
                    file_id=f["_id"],
                    display_name=f["display_name"],
                    model_id=vision_fallback_model,
                    status="success",
                    text=cached,
                    error=None,
                    timestamp=datetime.now(timezone.utc),
                ))
                continue

            # Cache miss — call the vision model.
            await emit_event(ChatVisionDescriptionEvent(
                correlation_id=correlation_id,
                file_id=f["_id"],
                display_name=f["display_name"],
                model_id=vision_fallback_model,
                status="pending",
                text=None,
                error=None,
                timestamp=datetime.now(timezone.utc),
            ))
            try:
                text = await describe_image(
                    user_id, vision_fallback_model, f["data"], f["media_type"],
                )
            except VisionFallbackError as exc:
                _log.warning(
                    "vision fallback failed for file=%s model=%s: %s",
                    f["_id"], vision_fallback_model, exc,
                )
                parts.append(ContentPart(
                    type="text",
                    text=f"\n[Image: {f['display_name']} — vision fallback failed]",
                ))
                await emit_event(ChatVisionDescriptionEvent(
                    correlation_id=correlation_id,
                    file_id=f["_id"],
                    display_name=f["display_name"],
                    model_id=vision_fallback_model,
                    status="error",
                    text=None,
                    error=str(exc),
                    timestamp=datetime.now(timezone.utc),
                ))
                continue

            await store_vision_description(
                f["_id"], user_id, vision_fallback_model, text,
            )
            parts.append(ContentPart(
                type="text",
                text=f"\n[Image description for {f['display_name']} (via {vision_fallback_model}):\n{text}\n]",
            ))
            snapshots.append({
                "file_id": f["_id"],
                "display_name": f["display_name"],
                "model_id": vision_fallback_model,
                "text": text,
            })
            await emit_event(ChatVisionDescriptionEvent(
                correlation_id=correlation_id,
                file_id=f["_id"],
                display_name=f["display_name"],
                model_id=vision_fallback_model,
                status="success",
                text=text,
                error=None,
                timestamp=datetime.now(timezone.utc),
            ))

        elif f.get("data"):
            text_content = f["data"].decode("utf-8", errors="replace")
            parts.append(ContentPart(
                type="text",
                text=f"\n--- {f['display_name']} ---\n{text_content}",
            ))

    return parts, snapshots, None
```

- [ ] **Step 3: Replace the inline block in `run_inference`**

In `run_inference`, locate the block at lines 168-191 (the `if attachment_ids:` block). Replace it with:

```python
        attachment_ids = last_msg.get("attachment_ids")
        new_msg_vision_snapshots: list[dict] = []
        if attachment_ids:
            files = await get_files_by_ids(attachment_ids, user_id)
            vision_fallback_model = (
                persona_for_resolve.get("vision_fallback_model")
                if persona_for_resolve else None
            )
            extra_parts, new_msg_vision_snapshots, _ = await _resolve_image_attachments_for_inference(
                user_id=user_id,
                files=files,
                supports_vision=await get_model_supports_vision(provider_id, model_slug),
                vision_fallback_model=vision_fallback_model,
                emit_event=emit_fn,
                correlation_id=correlation_id,
            )
            last_msg_parts.extend(extra_parts)
```

Note: at this point `correlation_id` and `emit_fn` are not yet defined (they are created later in the function). Move their definitions above this block. Specifically, move these lines from lower in the function to just before the `if history_docs:` block:

```python
    correlation_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[correlation_id] = cancel_event

    manager = get_manager()
    event_bus = get_event_bus()

    async def emit_fn(event) -> None:
        event_dict = event.model_dump(mode="json")
        event_type = event_dict.get("type", "")

        await event_bus.publish(
            event_type,
            event,
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
```

Delete the now-duplicate definitions further down in the function.

- [ ] **Step 4: Persist the snapshots in `save_fn`**

In `save_fn` (around lines 248-289), pass `vision_descriptions_used=new_msg_vision_snapshots or None` through to `repo.save_message`. **However**, the snapshot belongs to the **user** message, not the assistant message. Since `save_fn` saves the assistant message, we instead persist the snapshot on the user message that was already written.

Add this after the `if attachment_ids:` block in step 3:

```python
            if new_msg_vision_snapshots:
                await repo.update_message_vision_snapshots(
                    last_msg["_id"], new_msg_vision_snapshots,
                )
```

- [ ] **Step 5: Add `update_message_vision_snapshots` to the repository**

In `backend/modules/chat/_repository.py`, after `update_message_content`, add:

```python
    async def update_message_vision_snapshots(
        self, message_id: str, snapshots: list[dict],
    ) -> None:
        """Persist vision-description snapshots on a user message after inference setup."""
        await self._messages.update_one(
            {"_id": message_id},
            {"$set": {"vision_descriptions_used": snapshots}},
        )
```

- [ ] **Step 6: Update history-replay to use stored snapshots**

In the history-replay loop (lines 153-162), after the `attachment_refs` handling, also include any stored snapshots:

```python
        snaps = doc.get("vision_descriptions_used")
        if snaps:
            for s in snaps:
                content_parts_list.append(
                    ContentPart(
                        type="text",
                        text=f"\n[Image description for {s['display_name']} (via {s['model_id']}):\n{s['text']}\n]",
                    )
                )
```

- [ ] **Step 7: Run the orchestrator vision-fallback tests**

Run: `uv run pytest tests/test_chat_orchestrator_vision_fallback.py -v`
Expected: 6 passed.

- [ ] **Step 8: Verify the file compiles**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py backend/modules/chat/_repository.py`
Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/chat/_repository.py
git commit -m "Integrate vision fallback path and history-replay snapshots into orchestrator"
```

---

### Task 24: Add `Topics.CHAT_VISION_DESCRIPTION` to the WS event whitelist

**Files:**
- Modify: WS event bus / fanout config (location depends on existing structure)

The repo's recent commit `d6b7bc7 EventBus: whitelist persona.reordered for user fanout` shows there is a per-event-type whitelist for user fanout. The new vision description event must be added to that whitelist so it reaches the user's WS connection.

- [ ] **Step 1: Locate the whitelist**

Run: `uv run rg "PERSONA_REORDERED|persona.reordered" backend/ws/ shared/`
Note the file and line where the whitelist is defined.

- [ ] **Step 2: Add the new topic**

In the same place that lists the whitelisted event types for user fanout, add `Topics.CHAT_VISION_DESCRIPTION` (or its string `"chat.vision.description"`, depending on the existing pattern). Follow the exact convention used by surrounding entries.

- [ ] **Step 3: Verify file compiles**

Run: `uv run python -m py_compile <the modified file>`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add <modified file>
git commit -m "EventBus: whitelist chat.vision.description for user fanout"
```

---

## Phase 4 — Frontend Soft-CoT and shared types

### Task 25: Frontend persona types

**Files:**
- Modify: `frontend/src/core/types/persona.ts`

- [ ] **Step 1: Add fields to all three interfaces**

In `PersonaDto`, after `reasoning_enabled: boolean`, add:

```typescript
  soft_cot_enabled: boolean;
  vision_fallback_model: string | null;
```

In `CreatePersonaRequest`, after `reasoning_enabled?: boolean;`, add:

```typescript
  soft_cot_enabled?: boolean;
  vision_fallback_model?: string | null;
```

In `UpdatePersonaRequest`, after `reasoning_enabled?: boolean;`, add:

```typescript
  soft_cot_enabled?: boolean;
  vision_fallback_model?: string | null;
```

- [ ] **Step 2: Verify TypeScript still compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors (existing errors, if any, must not change).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/types/persona.ts
git commit -m "Add soft_cot_enabled and vision_fallback_model to frontend persona types"
```

---

### Task 26: PersonaOverlay default — extend with new fields

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Extend the default**

In `DEFAULT_PERSONA` (around line 35), after `reasoning_enabled: false,`, add:

```typescript
  soft_cot_enabled: false,
  vision_fallback_model: null,
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Extend DEFAULT_PERSONA with new persona fields"
```

---

### Task 27: EditTab — Soft-CoT toggle

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`

- [ ] **Step 1: Add state for the new toggle**

After the `const [reasoningEnabled, setReasoningEnabled] = useState(persona.reasoning_enabled)` line, add:

```typescript
  const [softCotEnabled, setSoftCotEnabled] = useState(persona.soft_cot_enabled)
```

- [ ] **Step 2: Compute Soft-CoT availability**

After the existing `useEffect` that loads model capabilities, add this derived value just before `const isDirty = ...`:

```typescript
  // Soft-CoT is offered when the model has no native reasoning, OR when it
  // has native reasoning but the user has Hard-CoT off. The toggle is greyed
  // when Hard-CoT is currently active for this persona.
  const softCotDisabled = canReason && reasoningEnabled
```

- [ ] **Step 3: Add to dirty check and save payload**

In `isDirty`, append:

```typescript
    || softCotEnabled !== persona.soft_cot_enabled
```

In `handleSave`'s `data` object, after `reasoning_enabled: reasoningEnabled,`, add:

```typescript
    soft_cot_enabled: softCotEnabled,
```

- [ ] **Step 4: Render the toggle**

In the toggles block (around lines 339-356), after the Reasoning `<Toggle>` and before the NSFW one, add:

```typescript
          <Toggle
            label="Soft Chain-of-Thought"
            description={
              softCotDisabled
                ? "Disabled while native reasoning is active"
                : "Ask the model to reason inside <think>...</think> blocks"
            }
            value={softCotEnabled}
            onChange={setSoftCotEnabled}
            chakraHex={chakra.hex}
            disabled={softCotDisabled}
          />
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Add Soft-CoT toggle to persona EditTab"
```

---

## Phase 5 — Frontend vision fallback

### Task 28: Add vision fallback dropdown to EditTab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`
- Inspect: `frontend/src/core/api/llm.ts` (to find the model-list shape)

- [ ] **Step 1: Inspect the model-list API**

Run: `cat frontend/src/core/api/llm.ts | head -80`
Note the type used by `llmApi.listModels(providerId)` for each model entry — specifically the `model_id`, `display_name`, and `supports_vision` fields. We will need a "list all models from all providers with `supports_vision=true`" call. If the existing API has a `listAll` or equivalent, use it. If not, fall back to fetching per registered provider in parallel.

- [ ] **Step 2: Add state and load vision-capable models**

After the existing `const [softCotEnabled, ...] = useState(...)` line, add:

```typescript
  const [visionFallbackModel, setVisionFallbackModel] = useState<string | null>(persona.vision_fallback_model)
  const [visionCapableModels, setVisionCapableModels] = useState<Array<{ unique_id: string; display_name: string; provider_id: string }>>([])
```

After the existing `useEffect` for loading capabilities, add a second `useEffect`:

```typescript
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        // If a "list all" endpoint exists, use it. Otherwise iterate
        // ADAPTER_REGISTRY-equivalent on the frontend (e.g. via llmApi.listProviders).
        const providers = await llmApi.listProviders()
        const all = await Promise.all(
          providers.map((p) => llmApi.listModels(p.id).catch(() => [])),
        )
        if (cancelled) return
        const flat = all.flat().filter((m) => m.supports_vision)
        setVisionCapableModels(flat.map((m) => ({
          unique_id: m.unique_id,
          display_name: m.display_name,
          provider_id: m.provider_id,
        })))
      } catch {
        if (!cancelled) setVisionCapableModels([])
      }
    }
    load()
    return () => { cancelled = true }
  }, [])
```

If `llmApi.listProviders` does not exist, replace the body with whatever existing pattern the codebase uses to enumerate providers (look in `frontend/src/core/api/llm.ts` and related stores). The goal is "all vision-capable models, grouped by provider" — use the simplest available primitive.

- [ ] **Step 3: Compute visibility**

The dropdown should only render when the persona's main model has `supports_vision=false`. Reuse the existing `useEffect` that loads `canReason` to also set a `canSeeImages` flag:

Find the `setCanReason(model?.supports_reasoning ?? false)` line inside the existing `useEffect`. Add immediately below it:

```typescript
        setCanSeeImages(model?.supports_vision ?? false)
```

Add the state declaration alongside `canReason`:

```typescript
  const [canSeeImages, setCanSeeImages] = useState(true)
```

Inside `handleModelSelect`, after `setCanUseTools(model.supports_tool_calls)`, add:

```typescript
    setCanSeeImages((model as any).supports_vision ?? false)
```

(Cast is acceptable here because the existing inline type does not currently include `supports_vision`. If the type can be extended cleanly, prefer that.)

- [ ] **Step 4: Add to dirty check and save payload**

In `isDirty`, append:

```typescript
    || visionFallbackModel !== persona.vision_fallback_model
```

In `handleSave`'s `data` object, after `soft_cot_enabled: softCotEnabled,`, add:

```typescript
    vision_fallback_model: visionFallbackModel,
```

- [ ] **Step 5: Render the dropdown when applicable**

In the toggles block, after the Soft-CoT toggle and before NSFW, insert:

```typescript
          {!canSeeImages && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[11px] text-white/40 uppercase tracking-wider">
                Vision fallback
              </label>
              <select
                value={visionFallbackModel ?? ""}
                onChange={(e) => setVisionFallbackModel(e.target.value || null)}
                style={{
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${chakra.hex}26`,
                  borderRadius: 8,
                  color: 'rgba(255,255,255,0.85)',
                  fontSize: 13,
                  padding: '8px 12px',
                  outline: 'none',
                }}
              >
                <option value="">No fallback</option>
                {visionCapableModels.map((m) => (
                  <option key={m.unique_id} value={m.unique_id}>
                    {m.provider_id} — {m.display_name}
                  </option>
                ))}
              </select>
              <span className="text-[11px] text-white/45">
                Used to describe images for this non-vision model.
              </span>
            </div>
          )}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Add vision fallback dropdown to persona EditTab"
```

---

### Task 29: Frontend topic constant + chat DTO

**Files:**
- Modify: `frontend/src/core/types/events.ts`
- Modify: `frontend/src/core/api/chat.ts`

- [ ] **Step 1: Add the topic constant**

In `frontend/src/core/types/events.ts`, in the `Topics` const object, after `CHAT_STREAM_ERROR: "chat.stream.error",`, add:

```typescript
  CHAT_VISION_DESCRIPTION: "chat.vision.description",
```

- [ ] **Step 2: Add `vision_descriptions_used` to ChatMessageDto**

In `frontend/src/core/api/chat.ts`, define a new exported type and extend `ChatMessageDto`:

```typescript
interface VisionDescriptionSnapshot {
  file_id: string
  display_name: string
  model_id: string
  text: string
}
```

In `ChatMessageDto`, after `knowledge_context: RetrievedChunkDto[] | null`, add:

```typescript
  vision_descriptions_used: VisionDescriptionSnapshot[] | null
```

Add `VisionDescriptionSnapshot` to the `export type` line at the bottom of the file.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/types/events.ts frontend/src/core/api/chat.ts
git commit -m "Add CHAT_VISION_DESCRIPTION topic and vision snapshot types"
```

---

### Task 30: Chat store — vision description map

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`

The store needs to hold live vision descriptions keyed by `(correlation_id, file_id)` so the UI can render the live block during a streaming user message before the persisted message exists.

- [ ] **Step 1: Read the current store**

Run: `cat frontend/src/core/store/chatStore.ts | head -100`
Note the structure (Zustand store with state slice and actions). Look for fields like `streamingThinking`, `streamingContent` — the new field follows the same pattern.

- [ ] **Step 2: Add state slice**

In the state interface, add:

```typescript
  visionDescriptions: Record<string, {
    file_id: string
    display_name: string
    model_id: string
    status: 'pending' | 'success' | 'error'
    text: string | null
    error: string | null
  }>
```

The key is `${correlation_id}:${file_id}`.

- [ ] **Step 3: Add an action**

```typescript
  upsertVisionDescription: (
    correlationId: string,
    payload: {
      file_id: string
      display_name: string
      model_id: string
      status: 'pending' | 'success' | 'error'
      text: string | null
      error: string | null
    },
  ) => void
```

In the implementation:

```typescript
  upsertVisionDescription: (correlationId, payload) => set((state) => ({
    visionDescriptions: {
      ...state.visionDescriptions,
      [`${correlationId}:${payload.file_id}`]: payload,
    },
  })),
```

Initialise `visionDescriptions: {}` in the initial state.

Also clear it when `startStreaming` is called for a new correlation, to avoid stale entries from previous streams. In the `startStreaming` action, add `visionDescriptions: {}` to the state reset.

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts
git commit -m "Add visionDescriptions slice to chat store"
```

---

### Task 31: useChatStream — handle CHAT_VISION_DESCRIPTION events

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`

- [ ] **Step 1: Add a case for the new event**

In the `switch (event.type)` block, after `case Topics.CHAT_THINKING_DELTA: { ... }`, add:

```typescript
        case Topics.CHAT_VISION_DESCRIPTION: {
          getStore().upsertVisionDescription(event.correlation_id, {
            file_id: p.file_id as string,
            display_name: p.display_name as string,
            model_id: p.model_id as string,
            status: p.status as 'pending' | 'success' | 'error',
            text: (p.text as string | null) ?? null,
            error: (p.error as string | null) ?? null,
          })
          break
        }
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Subscribe useChatStream to CHAT_VISION_DESCRIPTION events"
```

---

### Task 32: VisionDescriptionBlock component — failing test

**Files:**
- Create: `frontend/src/features/chat/__tests__/VisionDescriptionBlock.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { VisionDescriptionBlock } from '../VisionDescriptionBlock'

describe('VisionDescriptionBlock', () => {
  it('renders pending state with model name', () => {
    render(
      <VisionDescriptionBlock
        status="pending"
        modelId="ollama_cloud:mistral"
        text={null}
        error={null}
      />,
    )
    expect(screen.getByText(/mistral/i)).toBeInTheDocument()
    expect(screen.getByText(/describing/i)).toBeInTheDocument()
  })

  it('renders success state with collapsible description', () => {
    render(
      <VisionDescriptionBlock
        status="success"
        modelId="ollama_cloud:mistral"
        text="A red rose on a wooden table."
        error={null}
      />,
    )
    // Default collapsed — click to expand
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/red rose/i)).toBeInTheDocument()
  })

  it('renders error state', () => {
    render(
      <VisionDescriptionBlock
        status="error"
        modelId="ollama_cloud:mistral"
        text={null}
        error="vision fallback failed"
      />,
    )
    expect(screen.getByText(/vision fallback failed/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/VisionDescriptionBlock.test.tsx`
Expected: fails because the component does not exist yet.

- [ ] **Step 3: Commit failing test**

```bash
git add frontend/src/features/chat/__tests__/VisionDescriptionBlock.test.tsx
git commit -m "Add failing tests for VisionDescriptionBlock"
```

---

### Task 33: Implement VisionDescriptionBlock

**Files:**
- Create: `frontend/src/features/chat/VisionDescriptionBlock.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useState } from 'react'

interface VisionDescriptionBlockProps {
  status: 'pending' | 'success' | 'error'
  modelId: string
  text: string | null
  error: string | null
}

export function VisionDescriptionBlock({
  status,
  modelId,
  text,
  error,
}: VisionDescriptionBlockProps) {
  const [expanded, setExpanded] = useState(false)
  const modelLabel = modelId.split(':').slice(1).join(':') || modelId

  if (status === 'pending') {
    return (
      <div className="mt-1 flex items-center gap-2 rounded-md border border-white/8 bg-white/3 px-2 py-1 text-[11px] text-white/50">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-white/40" />
        Describing image with <span className="font-mono">{modelLabel}</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div
        className="mt-1 flex items-center gap-2 rounded-md border px-2 py-1 text-[11px]"
        style={{
          background: 'rgba(243, 139, 168, 0.06)',
          borderColor: 'rgba(243, 139, 168, 0.3)',
          color: 'rgba(243, 139, 168, 0.85)',
        }}
      >
        <span aria-hidden>⚠</span>
        {error ?? 'Vision fallback failed'} — please resend the message
      </div>
    )
  }

  return (
    <div className="mt-1 rounded-md border border-white/8 bg-white/3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-2 py-1 text-[11px] text-white/55 hover:text-white/75"
      >
        <span>
          Vision description{' '}
          <span className="font-mono text-white/35">via {modelLabel}</span>
        </span>
        <span aria-hidden>{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className="border-t border-white/6 px-2 py-1.5 text-[12px] leading-relaxed text-white/70 whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/VisionDescriptionBlock.test.tsx`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/VisionDescriptionBlock.tsx
git commit -m "Implement VisionDescriptionBlock"
```

---

### Task 34: Wire VisionDescriptionBlock into UserBubble

**Files:**
- Modify: `frontend/src/features/chat/UserBubble.tsx`

- [ ] **Step 1: Extend the props**

```typescript
interface UserBubbleProps {
  content: string
  attachments?: AttachmentRefDto[] | null
  visionDescriptionsUsed?: VisionDescriptionSnapshot[] | null
  liveVisionDescriptions?: Record<string, {
    status: 'pending' | 'success' | 'error'
    model_id: string
    text: string | null
    error: string | null
  }>
  onEdit: (newContent: string) => void
  isEditable: boolean
  isBookmarked?: boolean
  onBookmark?: () => void
}
```

Import `VisionDescriptionSnapshot` at the top:

```typescript
import type { AttachmentRefDto, VisionDescriptionSnapshot } from '../../core/api/chat'
import { VisionDescriptionBlock } from './VisionDescriptionBlock'
```

- [ ] **Step 2: Render a vision block per image attachment**

In the existing `attachments.map(...)` block, replace the chip render with:

```typescript
              {attachments.map((att) => {
                const isImage = att.media_type.startsWith('image/')
                const persistedSnap = visionDescriptionsUsed?.find(
                  (s) => s.file_id === att.file_id,
                )
                const liveSnap = liveVisionDescriptions?.[att.file_id]
                const visionState = liveSnap
                  ? liveSnap
                  : persistedSnap
                    ? {
                        status: 'success' as const,
                        model_id: persistedSnap.model_id,
                        text: persistedSnap.text,
                        error: null,
                      }
                    : null
                return (
                  <div key={att.file_id} className="flex flex-col">
                    <AttachmentChip attachment={att} />
                    {isImage && visionState && (
                      <VisionDescriptionBlock
                        status={visionState.status}
                        modelId={visionState.model_id}
                        text={visionState.text}
                        error={visionState.error}
                      />
                    )}
                  </div>
                )
              })}
```

- [ ] **Step 3: Pass props from MessageList**

Open `frontend/src/features/chat/MessageList.tsx`. In the `if (msg.role === 'user')` branch, locate the `<UserBubble ... />` call (line 75-76) and extend it:

```typescript
                <UserBubble
                  content={msg.content}
                  attachments={msg.attachments}
                  visionDescriptionsUsed={msg.vision_descriptions_used}
                  liveVisionDescriptions={liveDescriptionsForMessage(msg.id)}
                  onEdit={(newContent) => onEdit(msg.id, newContent)}
                  isEditable={!isStreaming}
                  isBookmarked={isBm}
                  onBookmark={() => onBookmark(msg.id)}
                />
```

The `liveDescriptionsForMessage` helper is `undefined` for persisted messages (they use the snapshot). For the **streaming user message** (the last user message during streaming), pull from the chat store. Add at the top of the component body:

```typescript
  const visionDescriptions = useChatStore((s) => s.visionDescriptions)
  const correlationId = useChatStore((s) => s.correlationId)

  function liveDescriptionsForMessage(messageId: string) {
    // Live descriptions only apply to the most recent user message during a
    // currently active stream. Persisted messages use vision_descriptions_used.
    if (!correlationId) return undefined
    const lastUserIdx = messages.findLastIndex((m) => m.role === 'user')
    if (lastUserIdx === -1 || messages[lastUserIdx].id !== messageId) return undefined
    const result: Record<string, {
      status: 'pending' | 'success' | 'error'
      model_id: string
      text: string | null
      error: string | null
    }> = {}
    for (const [key, payload] of Object.entries(visionDescriptions)) {
      const [corr, fileId] = key.split(':')
      if (corr === correlationId) {
        result[fileId] = {
          status: payload.status,
          model_id: payload.model_id,
          text: payload.text,
          error: payload.error,
        }
      }
    }
    return result
  }
```

Add the import at the top of `MessageList.tsx`:

```typescript
import { useChatStore } from '../../core/store/chatStore'
```

- [ ] **Step 4: Run the frontend test suite**

Run: `cd frontend && pnpm vitest run`
Expected: no regressions in existing tests; new VisionDescriptionBlock test passes.

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/UserBubble.tsx frontend/src/features/chat/MessageList.tsx
git commit -m "Render VisionDescriptionBlock per image attachment in UserBubble"
```

---

## Phase 6 — Manual scenarios, build verification, finishing

### Task 35: Soft-CoT manual LLM scenario

**Files:**
- Create: `tests/llm_scenarios/soft_cot_mistral.json`

- [ ] **Step 1: Look at an existing scenario for the format**

Run: `cat tests/llm_scenarios/simple_hello.json 2>/dev/null || ls tests/llm_scenarios/`
Use the first existing file as a template for the JSON shape.

- [ ] **Step 2: Create the scenario**

Use the same JSON shape as the existing files. Set:
- `model`: a Mistral model on Ollama Cloud (e.g. `mistral-large` or similar — pick whichever the user has access to)
- `system`: the actual `SOFT_COT_INSTRUCTIONS` constant prepended to a small persona prompt like `"You are a thoughtful assistant."`
- `messages`: two example user turns:
  - One analytical: `"Explain why the sky is blue, step by step."`
  - One relational: `"My friend cancelled our plans for the third time this month and said 'sorry, busy week'. Should I be worried?"`

The exact JSON shape depends on the existing convention — copy it from the simplest existing scenario file.

- [ ] **Step 3: Commit**

```bash
git add tests/llm_scenarios/soft_cot_mistral.json
git commit -m "Add manual LLM scenario for Soft-CoT prompt tuning"
```

---

### Task 36: Vision fallback manual LLM scenario

**Files:**
- Create: `tests/llm_scenarios/vision_fallback_mistral.json`

- [ ] **Step 1: Create the scenario**

Same JSON shape as Task 35. Set:
- `model`: a Mistral vision-capable model (e.g. `pixtral-large` or similar)
- `system`: the `_VISION_FALLBACK_SYSTEM_PROMPT` from `_vision_fallback.py`
- `messages`: a single user turn with a small base64-encoded test image (a placeholder note in the JSON value is fine if the harness supports loading from a path)

- [ ] **Step 2: Commit**

```bash
git add tests/llm_scenarios/vision_fallback_mistral.json
git commit -m "Add manual LLM scenario for vision fallback model tuning"
```

---

### Task 37: Run the full backend test suite

- [ ] **Step 1: Run pytest**

Run: `uv run pytest tests/ -v`
Expected: all tests pass (including all new tests added in this plan).

- [ ] **Step 2: If anything fails, fix it before proceeding**

Diagnose failures, fix the offending tasks, and re-run until clean.

---

### Task 38: Run the frontend build

- [ ] **Step 1: Run the build**

Run: `cd frontend && pnpm run build`
Expected: build completes without errors.

- [ ] **Step 2: Run the frontend test suite**

Run: `cd frontend && pnpm vitest run`
Expected: all tests pass.

---

### Task 39: Manual smoke test against a live system (optional)

- [ ] **Step 1: Bring up the stack**

Run: `docker compose up -d`

- [ ] **Step 2: Soft-CoT smoke**

In the UI, create a persona bound to a non-reasoning model, enable Soft-CoT in the EditTab, send a question that benefits from step-by-step thinking. Verify the thinking block appears in the assistant message and that the parser correctly separates the `<think>` content.

- [ ] **Step 3: Vision fallback smoke**

In the UI, create a persona bound to a non-vision model (e.g. a Zhipu GLM frontier model). In the EditTab, set the vision fallback to a Mistral vision model. Attach a flower image to a chat message and send it. Verify:
  - the pending block appears under the image immediately
  - it transitions to the success state with a description
  - the assistant's reply references the flower correctly
  - reloading the session still shows the description block (history snapshot)
  - sending a follow-up message that references "the flower" works (history-replay path)

- [ ] **Step 4: Cache smoke**

Send the same image a second time in a new message. Verify no second vision call is made (no pending state, immediate success block from cache).

---

### Task 40: Final commit and merge to master

- [ ] **Step 1: Ensure working tree is clean**

Run: `git status`
Expected: clean working tree.

- [ ] **Step 2: Merge to master**

Per the project's `## Implementation defaults` rule (`always merge to master after implementation`), run:

```bash
git checkout master
git merge --no-ff <feature-branch>
```

Or, if the work is already on master, this step is a no-op.

---

## Self-review checklist (run after the plan is complete)

1. **Soft-CoT spec coverage:**
   - PersonaDocument field → Tasks 9, 10, 11
   - DTO fields → Task 3
   - Visibility helper → Tasks 5, 6
   - Curated prompt block → Task 5
   - Prompt assembler injection → Tasks 12, 13, 14
   - Streaming `<think>` parser → Tasks 7, 8
   - Parser wiring in both inference paths → Task 15
   - Frontend toggle with Hard-CoT-aware disable → Task 27

2. **Vision fallback spec coverage:**
   - PersonaDocument field → Tasks 9, 10, 11
   - DTO fields → Task 3
   - Storage cache field + repo methods + cross-module API → Tasks 16, 17
   - ChatMessageDocument snapshot field + persist + read → Tasks 18, 19, 23
   - Vision runner with retry-once → Tasks 20, 21
   - Orchestrator integration with cache hit/miss/error paths → Tasks 22, 23
   - Multiple-image-per-message handling → Task 22 (multi test)
   - History replay using snapshot → Task 23 step 6
   - New event class + topic + WS whitelist → Tasks 1, 2, 24
   - Frontend dropdown with vision-only filter and persona-conditional render → Task 28
   - Frontend topic + DTO type extension → Task 29
   - Chat store live map → Task 30
   - WS handler subscription → Task 31
   - VisionDescriptionBlock component (3 states) → Tasks 32, 33
   - UserBubble integration with live and persisted variants → Task 34

3. **Tests:**
   - Soft-CoT visibility → Task 6
   - Soft-CoT prompt assembly (4 visibility cases) → Task 12
   - Soft-CoT parser (7 scenarios) → Task 7
   - Storage cache (3 scenarios) → Task 16
   - Vision runner (success, retry, exhaust) → Task 20
   - Orchestrator vision fallback (6 scenarios) → Task 22
   - Frontend VisionDescriptionBlock (3 states) → Task 32
   - Manual scenarios → Tasks 35, 36

4. **Out-of-scope items from the spec are NOT in the plan:**
   - Per-persona Soft-CoT prompt overrides ✓ not present
   - Global default vision fallback ✓ not present
   - Retroactive vision fallback for legacy messages ✓ not present
   - Multi-image batching ✓ not present (one call per image is explicit)

5. **Type consistency check:**
   - `is_soft_cot_active(soft_cot_enabled, supports_reasoning, reasoning_enabled)` — same signature in helper (Task 5), tests (Task 6), assembler call (Task 13), orchestrator wiring (Task 15), WS handlers (Task 15)
   - `_resolve_image_attachments_for_inference(user_id, files, supports_vision, vision_fallback_model, emit_event, correlation_id) -> (parts, snapshots, None)` — same in tests (Task 22) and implementation (Task 23)
   - `describe_image(user_id, model_unique_id, image_bytes, media_type) -> str` — same in tests (Task 20) and implementation (Task 21)
   - `ChatVisionDescriptionEvent` field set: `correlation_id, file_id, display_name, model_id, status, text, error, timestamp` — consistent across event class (Task 2), orchestrator emission (Task 23), frontend store (Task 30), useChatStream (Task 31), VisionDescriptionBlock props (Tasks 32, 33)
