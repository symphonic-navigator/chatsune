# Claude Router Cache Breakpoints — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-persona Anthropic prompt-cache breakpoint support to the OpenRouter and nano-gpt adapters, driven by an `Off / 5m / 1h` toggle visible only when a Claude model is selected.

**Architecture:** Pure-function strategy library (`_anthropic_cache.py`) computes marker positions and TTLs from `(messages, ttl)`. The OpenAI-compat router adapters call it from `_build_chat_payload`, then pass per-message `cache_control` dicts into a slightly extended `_translate_message`. PersonaDto carries `anthropic_cache_ttl`; the chat orchestrator pipes that into `CompletionRequest`. Other adapters (xAI, Mistral, Ollama, Community) and non-Anthropic routes stay pass-through. Spec: `devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md`.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 (backend); Vite + React 18 + TypeScript + Tailwind (frontend); pytest + Vitest. Subagent-driven; feature branch.

---

## Files

**Created:**
- `backend/modules/llm/_adapters/_anthropic_cache.py` — strategy lib
- `backend/tests/modules/llm/adapters/test_anthropic_cache.py` — unit tests
- `backend/tests/modules/llm/adapters/test_anthropic_cache_emission_openrouter.py` — adapter integration
- `backend/tests/modules/llm/adapters/test_anthropic_cache_emission_nano_gpt.py` — adapter integration
- `frontend/src/features/llm/anthropicCache.ts` — TS mirror of `is_anthropic_model`
- `frontend/src/features/llm/__tests__/anthropicCache.test.ts` — TS unit test

**Modified:**
- `shared/dtos/inference.py` — add `anthropic_cache_ttl` to `CompletionRequest`
- `shared/dtos/persona.py` — add field to `PersonaDto` / `CreatePersonaDto` / `UpdatePersonaDto`
- `backend/modules/persona/_models.py` — add field to `PersonaDocument`
- `backend/modules/persona/_repository.py` — accept and persist field on create
- `backend/modules/persona/_handlers.py` — pass field through create / update paths
- `backend/modules/chat/_orchestrator.py:880` — pull persona setting into `CompletionRequest`
- `backend/modules/chat/_handlers_ws.py:697` — same
- `backend/modules/llm/_adapters/_openrouter_http.py` — `_translate_message` + `_build_chat_payload` + log line
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — `_translate_message` + `_build_chat_payload` + log line
- `frontend/src/core/types/persona.ts` — add field to interfaces
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — conditional dropdown

---

## Pre-Flight

### Task 0: Feature branch

- [ ] **Step 1: Verify clean working tree on master**

```bash
git status
```

Expected: `nothing to commit, working tree clean` and branch `master`.

- [ ] **Step 2: Create and switch to feature branch**

```bash
git checkout -b feat/anthropic-cache-breakpoints
```

Expected: `Switched to a new branch 'feat/anthropic-cache-breakpoints'`. (Per memory `feedback_feature_branches_default.md` — Chatsune dev setup auto-reloads backend/frontend on branch switch.)

---

## Phase A — Strategy Library

### Task 1: `is_anthropic_model` (TDD)

**Files:**
- Create: `backend/modules/llm/_adapters/_anthropic_cache.py`
- Test: `backend/tests/modules/llm/adapters/test_anthropic_cache.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/modules/llm/adapters/test_anthropic_cache.py`:

```python
"""Unit tests for the Anthropic cache strategy library."""
from __future__ import annotations

import pytest

from backend.modules.llm._adapters._anthropic_cache import is_anthropic_model


@pytest.mark.parametrize("model_id", [
    "anthropic/claude-3-7-sonnet-20250219",
    "~anthropic/claude-opus-4-1",
    "claude-haiku-4-5",
    "claude-3-7-sonnet-20250219",
    "anthropic/claude-3.5-sonnet-vision",
    "ANTHROPIC/Claude-Sonnet-4-5",
])
def test_is_anthropic_model_positive(model_id: str) -> None:
    assert is_anthropic_model(model_id)


@pytest.mark.parametrize("model_id", [
    "openai/gpt-4",
    "openai/gpt-4o",
    "meta/llama-3.3-70b",
    "mistral-large-latest",
    "anthropic/claude-instant-1",
    "meta/llama-claude-skin",
    "",
    "anthropic/",
    "claude",
])
def test_is_anthropic_model_negative(model_id: str) -> None:
    assert not is_anthropic_model(model_id)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v
```

Expected: collection error / `ImportError` because `_anthropic_cache.py` does not exist.

- [ ] **Step 3: Write minimal implementation**

`backend/modules/llm/_adapters/_anthropic_cache.py`:

```python
"""Anthropic prompt-cache strategy library.

Pure functions that decide whether a given model accepts Anthropic
``cache_control`` markers and where those markers should be placed
in a chat message list. Used by both the OpenRouter and nano-gpt
adapters, which translate the resulting positions into OpenAI-compat
``cache_control`` content-block dicts at request time.

Spec: devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md
"""

from __future__ import annotations

import re

# Match "claude" anywhere in the slug tail, followed by a haiku /
# sonnet / opus token at a word boundary. Older "claude-instant-*"
# slugs deliberately do not match — they predate cache_control
# support, so the negative case is correct behaviour.
_CLAUDE_RE = re.compile(r"claude.*\b(haiku|sonnet|opus)\b", re.IGNORECASE)


def is_anthropic_model(model_id: str) -> bool:
    """True iff ``model_id`` looks like a Claude model that accepts cache_control.

    Tolerant of router-specific slug shapes:

    * OpenRouter: ``anthropic/claude-…`` and the occasional
      ``~anthropic/claude-…`` (latter prefix observed on the OR
      catalogue, semantics unclear but harmless).
    * nano-gpt:   ``claude-3-7-sonnet-20250219`` (no vendor prefix).

    Strategy: take only the part after the last ``/`` (or the whole
    string if no ``/`` is present), then regex-match for
    ``claude.*haiku|sonnet|opus``.
    """
    tail = model_id.rsplit("/", 1)[-1]
    return bool(_CLAUDE_RE.search(tail))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_anthropic_cache.py \
        backend/tests/modules/llm/adapters/test_anthropic_cache.py
git commit -m "Add is_anthropic_model vendor detection for cache strategy"
```

### Task 2: `compute_cache_markers` (TDD)

**Files:**
- Modify: `backend/modules/llm/_adapters/_anthropic_cache.py`
- Modify: `backend/tests/modules/llm/adapters/test_anthropic_cache.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/modules/llm/adapters/test_anthropic_cache.py`:

```python
from backend.modules.llm._adapters._anthropic_cache import (
    BLOCK_SIZE,
    CacheMarker,
    compute_cache_markers,
)
from shared.dtos.inference import CompletionMessage, ContentPart


def _msg(role: str, text: str = "x") -> CompletionMessage:
    return CompletionMessage(
        role=role, content=[ContentPart(type="text", text=text)],
    )


def test_compute_markers_off_returns_empty() -> None:
    msgs = [_msg("system"), _msg("user")]
    assert compute_cache_markers(msgs, "off") == []


def test_compute_markers_empty_messages_returns_empty() -> None:
    assert compute_cache_markers([], "5m") == []


def test_compute_markers_single_user_message() -> None:
    # Only one user message — no system, no tail (len < 2 after the
    # tail check since tail_index would be -1).
    msgs = [_msg("user")]
    assert compute_cache_markers(msgs, "5m") == []


def test_compute_markers_system_only_with_one_user() -> None:
    # System + one user message: system marker, no tail (tail would
    # collide with system at index 0).
    msgs = [_msg("system"), _msg("user")]
    result = compute_cache_markers(msgs, "5m")
    assert result == [CacheMarker(message_index=0, ttl="1h")]


def test_compute_markers_5m_short_conversation() -> None:
    # 5 messages, ttl=5m → System + Tail (no block, n < BLOCK_SIZE)
    msgs = [_msg("system")] + [_msg("user"), _msg("assistant")] * 2
    assert len(msgs) == 5
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=3, ttl="5m"),
    ]


def test_compute_markers_5m_long_conversation_has_block() -> None:
    # 22 messages, ttl=5m → System + Block@15 (1h) + Tail@20 (5m).
    # last_block_end = (22 // 8) * 8 - 1 = 15.
    msgs = [_msg("system")] + [_msg("user")] * 21
    assert len(msgs) == 22
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=15, ttl="1h"),
        CacheMarker(message_index=20, ttl="5m"),
    ]


def test_compute_markers_1h_long_conversation_tail_is_1h() -> None:
    # Same shape as above but ttl=1h → tail switches to 1h.
    msgs = [_msg("system")] + [_msg("user")] * 21
    result = compute_cache_markers(msgs, "1h")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=15, ttl="1h"),
        CacheMarker(message_index=20, ttl="1h"),
    ]


def test_compute_markers_block_collides_with_tail_dedupes() -> None:
    # 9 messages: tail_index = 7, last_block_end = 7. Block placed,
    # tail dedupes (no double marker at index 7).
    msgs = [_msg("system")] + [_msg("user")] * 8
    assert len(msgs) == 9
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=7, ttl="1h"),
    ]


def test_compute_markers_block_at_end_minus_one_is_skipped() -> None:
    # 8 messages: last_block_end = 7, tail_index = 6. Block check
    # requires last_block_end < n - 1 (i.e. < 7), so block is NOT
    # placed. Result: System + Tail@6.
    msgs = [_msg("system")] + [_msg("user")] * 7
    assert len(msgs) == 8
    result = compute_cache_markers(msgs, "5m")
    assert result == [
        CacheMarker(message_index=0, ttl="1h"),
        CacheMarker(message_index=6, ttl="5m"),
    ]


def test_compute_markers_no_system_message() -> None:
    # First message is user, not system → no system marker.
    # 22 user/assistant messages. last_block_end = 15.
    msgs = [_msg("user")] * 22
    result = compute_cache_markers(msgs, "1h")
    assert result == [
        CacheMarker(message_index=15, ttl="1h"),
        CacheMarker(message_index=20, ttl="1h"),
    ]


def test_block_size_is_eight() -> None:
    assert BLOCK_SIZE == 8
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v
```

Expected: ImportError on `BLOCK_SIZE`, `CacheMarker`, `compute_cache_markers`.

- [ ] **Step 3: Implement strategy**

Append to `backend/modules/llm/_adapters/_anthropic_cache.py`:

```python
from dataclasses import dataclass
from typing import Literal

from shared.dtos.inference import CompletionMessage

CacheTtl = Literal["off", "5m", "1h"]
BlockTtl = Literal["5m", "1h"]

# Block-boundary stride. Static first-guess; observability data
# (see spec §10) drives any future re-tuning. One-line change, no
# migration impact — see spec §11.
BLOCK_SIZE = 8


@dataclass(frozen=True)
class CacheMarker:
    """Where to place a cache_control marker and at what TTL.

    ``message_index`` is the index into ``CompletionRequest.messages``
    of the message whose final content block carries the marker.
    """

    message_index: int
    ttl: BlockTtl


def compute_cache_markers(
    messages: list[CompletionMessage], ttl: CacheTtl,
) -> list[CacheMarker]:
    """Compute marker positions for an Anthropic-compatible request.

    Strategy (see spec §5.2):

    * **System** marker at index 0 if the first message is a system
      message — always 1h, regardless of the user's TTL choice.
    * **Block-boundary** marker at the last crossed BLOCK_SIZE-aligned
      message index — always 1h. Provides a long-pause fallback that
      survives 5m idle periods even in 5m-mode.
    * **Rolling tail** marker at ``len(messages) - 2`` (the last
      stable assistant turn boundary) — TTL = the user's choice.

    The 4th breakpoint slot is deliberately unused (spec §11).

    Returns an empty list for ``ttl == "off"`` or empty inputs. Marker
    list is in ascending message-index order.
    """
    if ttl == "off" or not messages:
        return []

    markers: list[CacheMarker] = []

    if messages[0].role == "system":
        markers.append(CacheMarker(message_index=0, ttl="1h"))

    n = len(messages)
    last_block_end = (n // BLOCK_SIZE) * BLOCK_SIZE - 1
    if last_block_end > 0 and last_block_end < n - 1:
        if not any(m.message_index == last_block_end for m in markers):
            markers.append(
                CacheMarker(message_index=last_block_end, ttl="1h"),
            )

    if n >= 2:
        tail_index = n - 2
        if tail_index > 0 and not any(
            m.message_index == tail_index for m in markers
        ):
            markers.append(CacheMarker(message_index=tail_index, ttl=ttl))

    return markers
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v
```

Expected: all tests pass (~26 total — Task 1's 15 + Task 2's 11).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_anthropic_cache.py \
        backend/tests/modules/llm/adapters/test_anthropic_cache.py
git commit -m "Add compute_cache_markers strategy for Anthropic prompt cache"
```

---

## Phase B — Shared Contracts

### Task 3: `anthropic_cache_ttl` on `CompletionRequest`

**Files:**
- Modify: `shared/dtos/inference.py:33-41`

- [ ] **Step 1: Read the current CompletionRequest definition**

```bash
PYTHONPATH=$(pwd) uv run python -c "from shared.dtos.inference import CompletionRequest; print(CompletionRequest.model_fields.keys())"
```

Expected: `dict_keys(['model', 'messages', 'temperature', 'tools', 'reasoning_enabled', 'supports_reasoning', 'cache_hint'])`.

- [ ] **Step 2: Add the field**

Edit `shared/dtos/inference.py`. Replace the `CompletionRequest` class with:

```python
class CompletionRequest(BaseModel):
    model: str                       # provider-specific model slug
    messages: list[CompletionMessage]
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None
    reasoning_enabled: bool = False
    supports_reasoning: bool = False  # model capability — adapter uses this to decide whether to send think param
    cache_hint: str | None = None     # provider-specific cache locality hint (e.g. session UUID for x-grok-conv-id)
    # Anthropic prompt-cache TTL — only honoured by the OpenRouter and
    # nano-gpt adapters when the model is a Claude family member.
    # Other adapters and non-Anthropic routes ignore the field. Default
    # ``"off"`` keeps existing call-sites and tests behaviourally
    # unchanged. See devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md.
    anthropic_cache_ttl: Literal["off", "5m", "1h"] = "off"
```

- [ ] **Step 3: Verify the import resolves**

```bash
PYTHONPATH=$(pwd) uv run python -c "from shared.dtos.inference import CompletionRequest; r = CompletionRequest(model='x', messages=[]); print(r.anthropic_cache_ttl)"
```

Expected: `off`.

- [ ] **Step 4: Run the full inference DTO unit tests if any exist**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests -k "completion_request or inference_dto" -v
```

Expected: pass (or "no tests collected" — also fine).

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/inference.py
git commit -m "Add anthropic_cache_ttl field to CompletionRequest"
```

### Task 4: `anthropic_cache_ttl` on Persona DTOs

**Files:**
- Modify: `shared/dtos/persona.py:54-148`

- [ ] **Step 1: Add the field to all three DTOs**

Edit `shared/dtos/persona.py`. Inside `PersonaDto` class body, add after the `reasoning_enabled` field block (right before `soft_cot_enabled: bool = False`):

```python
    # Anthropic prompt-cache TTL — only meaningful when the persona's
    # model is a Claude family member behind OpenRouter or nano-gpt.
    # Other models silently ignore the value. Frontend hides the
    # control unless the selected model passes ``isAnthropicModel``.
    # Default ``"off"`` keeps existing persona documents readable
    # (see CLAUDE.md §Data-Model Migrations).
    anthropic_cache_ttl: Literal["off", "5m", "1h"] = "off"
```

Inside `CreatePersonaDto`, add after `reasoning_enabled: bool = False`:

```python
    anthropic_cache_ttl: Literal["off", "5m", "1h"] = "off"
```

Inside `UpdatePersonaDto`, add after `reasoning_enabled: bool | None = None`:

```python
    anthropic_cache_ttl: Literal["off", "5m", "1h"] | None = None
```

- [ ] **Step 2: Verify imports and defaults**

```bash
PYTHONPATH=$(pwd) uv run python -c "
from shared.dtos.persona import PersonaDto, CreatePersonaDto, UpdatePersonaDto
print('PersonaDto:', PersonaDto.model_fields['anthropic_cache_ttl'].default)
print('CreatePersonaDto:', CreatePersonaDto.model_fields['anthropic_cache_ttl'].default)
print('UpdatePersonaDto:', UpdatePersonaDto.model_fields['anthropic_cache_ttl'].default)
"
```

Expected:
```
PersonaDto: off
CreatePersonaDto: off
UpdatePersonaDto: None
```

- [ ] **Step 3: Run any existing persona-DTO tests**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests -k "persona_dto or PersonaDto" -v
```

Expected: pass (or no tests collected).

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/persona.py
git commit -m "Add anthropic_cache_ttl field to Persona DTOs"
```

---

## Phase C — Persona Persistence

### Task 5: Persona document and repository

**Files:**
- Modify: `backend/modules/persona/_models.py`
- Modify: `backend/modules/persona/_repository.py:28-69, 200-220`

- [ ] **Step 1: Add field to `PersonaDocument`**

Edit `backend/modules/persona/_models.py`. After `reasoning_enabled: bool` (around line 16):

```python
    # Anthropic prompt-cache TTL — see shared.dtos.persona.PersonaDto.
    # Default ``"off"`` keeps pre-existing persona documents readable
    # (CLAUDE.md §Data-Model Migrations).
    anthropic_cache_ttl: str = "off"
```

(Stored as plain `str` in the document model — the public DTO already
constrains the literal values; mirroring `Literal` in the document
model would just duplicate validation.)

- [ ] **Step 2: Read the relevant repository sections**

The `create()` method around line 28 builds the document dict; the
`_doc_to_dto()` (or equivalent) reader maps documents back to DTOs.

```bash
grep -n "def create\|def find_by_id\|_doc_to_dto\|reasoning_enabled" backend/modules/persona/_repository.py | head -20
```

- [ ] **Step 3: Add `anthropic_cache_ttl` parameter to `create()`**

In `backend/modules/persona/_repository.py`, modify `create()`:

```python
    async def create(
        self,
        user_id: str,
        name: str,
        tagline: str,
        model_unique_id: str,
        system_prompt: str,
        temperature: float,
        reasoning_enabled: bool,
        nsfw: bool,
        colour_scheme: str,
        display_order: int,
        pinned: bool = False,
        profile_image: str | None = None,
        soft_cot_enabled: bool = False,
        vision_fallback_model: str | None = None,
        use_memory: bool = True,
        anthropic_cache_ttl: str = "off",
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "name": name,
            "tagline": tagline,
            "model_unique_id": model_unique_id,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "reasoning_enabled": reasoning_enabled,
            "soft_cot_enabled": soft_cot_enabled,
            "vision_fallback_model": vision_fallback_model,
            "use_memory": use_memory,
            "nsfw": nsfw,
            "colour_scheme": colour_scheme,
            "display_order": display_order,
            "monogram": "",
            "pinned": pinned,
            "profile_image": profile_image,
            "anthropic_cache_ttl": anthropic_cache_ttl,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc
```

- [ ] **Step 4: Confirm read path is field-tolerant**

The repository returns raw MongoDB dicts (see `find_by_id` line 71).
Pre-existing documents will return without `anthropic_cache_ttl`. The
DTO conversion at the handler boundary applies the `"off"` default,
and orchestrator code reads with `persona.get("anthropic_cache_ttl", "off")` (added in Task 7). No repository read change needed.

Sanity-check by scanning for `_doc_to_dto`-style helpers:

```bash
grep -n "PersonaDto(" backend/modules/persona/_handlers.py | head -5
```

If the handler builds `PersonaDto(**doc)`, the Pydantic default for
the missing key kicks in automatically. Otherwise, the orchestrator's
`.get()` default also covers it.

- [ ] **Step 5: Build verification**

```bash
uv run python -m py_compile backend/modules/persona/_models.py backend/modules/persona/_repository.py
```

Expected: no output (clean).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/persona/_models.py backend/modules/persona/_repository.py
git commit -m "Persist anthropic_cache_ttl on Persona documents"
```

---

## Phase D — Persona Handlers

### Task 6: Wire create / update endpoints

**Files:**
- Modify: `backend/modules/persona/_handlers.py`

- [ ] **Step 1: Locate the create handler**

```bash
grep -n "async def create_persona\|reasoning_enabled" backend/modules/persona/_handlers.py | head -20
```

The create handler typically calls `repo.create(...)` with explicit
parameters mirroring the `CreatePersonaDto`. Find that call site.

- [ ] **Step 2: Pass `anthropic_cache_ttl` into `create`**

At the `repo.create(...)` call, add the new keyword:

```python
    doc = await repo.create(
        user_id=user_id,
        name=dto.name,
        tagline=dto.tagline,
        model_unique_id=dto.model_unique_id,
        system_prompt=dto.system_prompt,
        temperature=dto.temperature,
        reasoning_enabled=dto.reasoning_enabled,
        nsfw=dto.nsfw,
        colour_scheme=dto.colour_scheme,
        display_order=dto.display_order,
        pinned=dto.pinned,
        profile_image=dto.profile_image,
        soft_cot_enabled=dto.soft_cot_enabled,
        vision_fallback_model=dto.vision_fallback_model,
        use_memory=dto.use_memory,
        anthropic_cache_ttl=dto.anthropic_cache_ttl,
    )
```

(Adjust kwarg names to match the actual signature in the handler —
do not invent fields. If the handler currently passes `dto.use_memory`
positionally, mirror that style for the new field.)

- [ ] **Step 3: Locate the update handler**

```bash
grep -n "async def update_persona\|model_fields_set" backend/modules/persona/_handlers.py | head -20
```

Updates use `dto.model_fields_set` to distinguish "field omitted"
from "field set to None" (see the `vision_fallback_model` and
`default_project_id` patterns).

- [ ] **Step 4: Plumb `anthropic_cache_ttl` through update**

Inside the update handler's field-mapping block, add a branch that
mirrors the existing pattern. Example (adapt to the handler's actual
shape — the existing `vision_fallback_model` block is the model):

```python
    if "anthropic_cache_ttl" in dto.model_fields_set:
        # ``None`` is not a valid persisted value — clamp to "off".
        # The DTO Optional only exists so omission is distinguishable
        # from explicit set; a client must never send null here.
        if dto.anthropic_cache_ttl is None:
            update["anthropic_cache_ttl"] = "off"
        else:
            update["anthropic_cache_ttl"] = dto.anthropic_cache_ttl
```

- [ ] **Step 5: Build verification**

```bash
uv run python -m py_compile backend/modules/persona/_handlers.py
```

Expected: clean.

- [ ] **Step 6: Smoke-run pure persona-module tests**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/persona -v
```

The only files in `backend/tests/modules/persona/` today are
`test_bump_last_used.py` and `test_migration_tts_provider_id.py`,
neither of which touches the persona create/update handler we just
modified. The smoke-run is to confirm we did not introduce import
errors in `_handlers.py`. Per memory `feedback_db_tests_on_host.md`
the live-DB tests live elsewhere (`backend/tests/integration/` and
`backend/tests/ws/test_sidecar_router.py`) — do **not** invoke
those on host.

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/persona/_handlers.py
git commit -m "Plumb anthropic_cache_ttl through Persona create/update handlers"
```

---

## Phase E — Chat Wiring

### Task 7: Pipe persona setting into `CompletionRequest` (orchestrator)

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py:880-888`

- [ ] **Step 1: Read the surrounding context**

```bash
sed -n '870,892p' backend/modules/chat/_orchestrator.py
```

Confirms the existing `CompletionRequest(...)` construction at
line 880 reads `persona.get("temperature")` etc.

- [ ] **Step 2: Add the new keyword**

Edit lines 880-888. Replace:

```python
    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=reasoning_enabled,
        supports_reasoning=supports_reasoning,
        tools=active_tools,
        cache_hint=session_id,
    )
```

with:

```python
    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=reasoning_enabled,
        supports_reasoning=supports_reasoning,
        tools=active_tools,
        cache_hint=session_id,
        anthropic_cache_ttl=(
            persona.get("anthropic_cache_ttl", "off") if persona else "off"
        ),
    )
```

- [ ] **Step 3: Build verification**

```bash
uv run python -m py_compile backend/modules/chat/_orchestrator.py
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Pass anthropic_cache_ttl from persona into orchestrator CompletionRequest"
```

### Task 8: Pipe persona setting into `CompletionRequest` (handlers_ws)

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py:697-705`

- [ ] **Step 1: Read the surrounding context**

```bash
sed -n '685,710p' backend/modules/chat/_handlers_ws.py
```

- [ ] **Step 2: Add the new keyword**

Replace lines 697-705:

```python
        request = CompletionRequest(
            model=model_slug,
            messages=messages,
            temperature=persona.get("temperature"),
            reasoning_enabled=persona.get("reasoning_enabled", False),
            supports_reasoning=supports_reasoning,
            tools=active_tools,
            cache_hint=session_id,
        )
```

with:

```python
        request = CompletionRequest(
            model=model_slug,
            messages=messages,
            temperature=persona.get("temperature"),
            reasoning_enabled=persona.get("reasoning_enabled", False),
            supports_reasoning=supports_reasoning,
            tools=active_tools,
            cache_hint=session_id,
            anthropic_cache_ttl=persona.get("anthropic_cache_ttl", "off"),
        )
```

- [ ] **Step 3: Build verification**

```bash
uv run python -m py_compile backend/modules/chat/_handlers_ws.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Pass anthropic_cache_ttl from persona in handlers_ws path"
```

(Vision-fallback, title-generation, and llm_harness call sites
intentionally retain the default `"off"` — those are one-shot
auxiliary calls where caching has no payoff.)

---

## Phase F — Adapter Marker Emission

### Task 9: OpenRouter adapter `_translate_message` extension (TDD)

**Files:**
- Create: `backend/tests/modules/llm/adapters/test_anthropic_cache_emission_openrouter.py`
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`

- [ ] **Step 1: Write the failing emission test**

Create `backend/tests/modules/llm/adapters/test_anthropic_cache_emission_openrouter.py`:

```python
"""Verify cache_control marker emission in the OpenRouter payload builder."""
from __future__ import annotations

from backend.modules.llm._adapters._openrouter_http import _build_chat_payload
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)


def _msg(role: str, text: str = "x") -> CompletionMessage:
    return CompletionMessage(
        role=role, content=[ContentPart(type="text", text=text)],
    )


def _request(
    model: str, messages: list[CompletionMessage], ttl: str,
) -> CompletionRequest:
    return CompletionRequest(
        model=model, messages=messages, anthropic_cache_ttl=ttl,
    )


def test_no_markers_when_ttl_off() -> None:
    msgs = [_msg("system"), _msg("user")] + [_msg("user")] * 20
    payload = _build_chat_payload(
        _request("anthropic/claude-sonnet-4.5", msgs, "off"),
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_no_markers_for_non_anthropic_model() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("openai/gpt-4o", msgs, "5m"),
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_5m_emission_on_long_anthropic_conversation() -> None:
    # 22 messages → System(0, 1h) + Block(15, 1h) + Tail(20, 5m).
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("anthropic/claude-sonnet-4.5", msgs, "5m"),
    )
    expected = {
        0: {"type": "ephemeral", "ttl": "1h"},
        15: {"type": "ephemeral", "ttl": "1h"},
        20: {"type": "ephemeral"},
    }
    for i, m in enumerate(payload["messages"]):
        if i in expected:
            assert isinstance(m["content"], list), (
                f"index {i} content must be list to carry cache_control"
            )
            assert m["content"][-1].get("cache_control") == expected[i], i
        else:
            content = m["content"]
            if isinstance(content, list):
                for block in content:
                    assert "cache_control" not in block, i


def test_1h_emission_makes_tail_1h() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("anthropic/claude-sonnet-4.5", msgs, "1h"),
    )
    tail = payload["messages"][20]
    assert tail["content"][-1].get("cache_control") == {
        "type": "ephemeral", "ttl": "1h",
    }


def test_marker_attaches_to_last_content_block_with_image() -> None:
    # Tail position must carry cache_control on the LAST block when
    # both text and image are present.
    msgs = [_msg("system")]
    for _ in range(20):
        msgs.append(_msg("user"))
    image_msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="hi"),
            ContentPart(
                type="image",
                data="aGVsbG8=",  # base64 'hello'
                media_type="image/png",
            ),
        ],
    )
    msgs.insert(20, image_msg)  # tail_index becomes 20
    assert len(msgs) == 22
    payload = _build_chat_payload(
        _request("anthropic/claude-sonnet-4.5", msgs, "5m"),
    )
    tail_blocks = payload["messages"][20]["content"]
    assert tail_blocks[-1]["type"] == "image_url"
    assert tail_blocks[-1].get("cache_control") == {"type": "ephemeral"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache_emission_openrouter.py -v
```

Expected: tests fail because `_translate_message` does not yet honour `cache_control`.

- [ ] **Step 3: Modify `_translate_message` to accept `cache_control`**

In `backend/modules/llm/_adapters/_openrouter_http.py`, replace the existing `_translate_message` (around lines 259-289):

```python
def _translate_message(
    msg: CompletionMessage,
    *,
    cache_control: dict | None = None,
) -> dict:
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    if cache_control is None and not image_parts:
        # Plain string content — more cache-friendly for non-Anthropic
        # routes that perform automatic prefix caching.
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.media_type};base64,{p.data}",
                },
            })
        if cache_control and content:
            # Anthropic convention: cache_control on the LAST content
            # block of the marked message — that block's index defines
            # the prefix endpoint that gets cached.
            content[-1]["cache_control"] = cache_control

    result: dict = {"role": msg.role, "content": content}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        result["tool_call_id"] = msg.tool_call_id
    return result
```

- [ ] **Step 4: Modify `_build_chat_payload` to compute and apply markers**

In the same file, locate `_build_chat_payload` (around line 292) and
add cache-marker computation. Replace the function with:

```python
def _build_chat_payload(request: CompletionRequest) -> dict:
    from backend.modules.llm._adapters._anthropic_cache import (
        compute_cache_markers,
        is_anthropic_model,
    )

    cc_by_index: dict[int, dict] = {}
    if (
        request.anthropic_cache_ttl != "off"
        and is_anthropic_model(request.model)
    ):
        for marker in compute_cache_markers(
            request.messages, request.anthropic_cache_ttl,
        ):
            cc_by_index[marker.message_index] = _to_cache_control(marker.ttl)

    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            _translate_message(m, cache_control=cc_by_index.get(i))
            for i, m in enumerate(request.messages)
        ],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    if request.supports_reasoning and not request.reasoning_enabled:
        payload["reasoning"] = {"exclude": True}
    return payload


def _to_cache_control(ttl: str) -> dict:
    # OpenAI-compat → Anthropic translation: 5m is the implicit
    # default when ``ttl`` is omitted; 1h must be set explicitly.
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}
```

- [ ] **Step 5: Run new tests to verify they pass**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache_emission_openrouter.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Run the full pre-existing OpenRouter test file to catch regressions**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -v
```

Expected: pass (no behavioural change for `anthropic_cache_ttl="off"` callers — that's the default for all existing test fixtures).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_anthropic_cache_emission_openrouter.py
git commit -m "Emit Anthropic cache_control markers from OpenRouter adapter"
```

### Task 10: Nano-GPT adapter `_translate_message` extension (TDD)

**Files:**
- Create: `backend/tests/modules/llm/adapters/test_anthropic_cache_emission_nano_gpt.py`
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`

- [ ] **Step 1: Write the failing emission test**

Create `backend/tests/modules/llm/adapters/test_anthropic_cache_emission_nano_gpt.py`:

```python
"""Verify cache_control marker emission in the nano-gpt payload builder."""
from __future__ import annotations

from backend.modules.llm._adapters._nano_gpt_http import _build_chat_payload
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)


def _msg(role: str, text: str = "x") -> CompletionMessage:
    return CompletionMessage(
        role=role, content=[ContentPart(type="text", text=text)],
    )


def _request(
    model: str, messages: list[CompletionMessage], ttl: str,
) -> CompletionRequest:
    return CompletionRequest(
        model=model, messages=messages, anthropic_cache_ttl=ttl,
    )


def test_no_markers_when_ttl_off() -> None:
    msgs = [_msg("system"), _msg("user")] + [_msg("user")] * 20
    payload = _build_chat_payload(
        _request("claude-3-7-sonnet-20250219", msgs, "off"),
        upstream_slug="claude-3-7-sonnet-20250219",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_no_markers_for_non_anthropic_model() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("gpt-4o", msgs, "5m"),
        upstream_slug="gpt-4o",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    for m in payload["messages"]:
        if isinstance(m["content"], list):
            for block in m["content"]:
                assert "cache_control" not in block


def test_5m_emission_on_long_anthropic_conversation_no_prefix_slug() -> None:
    # nano-gpt slugs lack the "anthropic/" prefix.
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("claude-3-7-sonnet-20250219", msgs, "5m"),
        upstream_slug="claude-3-7-sonnet-20250219",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    expected = {
        0: {"type": "ephemeral", "ttl": "1h"},
        15: {"type": "ephemeral", "ttl": "1h"},
        20: {"type": "ephemeral"},
    }
    for i, m in enumerate(payload["messages"]):
        if i in expected:
            assert isinstance(m["content"], list)
            assert m["content"][-1].get("cache_control") == expected[i], i
        else:
            content = m["content"]
            if isinstance(content, list):
                for block in content:
                    assert "cache_control" not in block, i


def test_1h_tail_is_explicit() -> None:
    msgs = [_msg("system")] + [_msg("user")] * 21
    payload = _build_chat_payload(
        _request("claude-haiku-4-5", msgs, "1h"),
        upstream_slug="claude-haiku-4-5",
        send_reasoning_flag=False,
        reasoning_enabled=False,
    )
    assert payload["messages"][20]["content"][-1].get("cache_control") == {
        "type": "ephemeral", "ttl": "1h",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache_emission_nano_gpt.py -v
```

Expected: failures — nano-gpt adapter has not yet been modified.

- [ ] **Step 3: Modify `_translate_message`**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`, replace the existing `_translate_message` (around lines 247-282) with the same shape as the OpenRouter version:

```python
def _translate_message(
    msg: CompletionMessage,
    *,
    cache_control: dict | None = None,
) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat message."""
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    if cache_control is None and not image_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.media_type};base64,{p.data}",
                },
            })
        if cache_control and content:
            content[-1]["cache_control"] = cache_control

    result: dict = {"role": msg.role, "content": content}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        result["tool_call_id"] = msg.tool_call_id
    return result
```

- [ ] **Step 4: Modify `_build_chat_payload`**

The existing nano-gpt `_build_chat_payload` takes extra reasoning-mode arguments (see file header doc). Extend it to compute markers and pass them through:

```python
def _build_chat_payload(
    request: CompletionRequest,
    upstream_slug: str,
    *,
    send_reasoning_flag: bool,
    reasoning_enabled: bool,
) -> dict:
    """Build an OpenAI-compatible chat-completions request body.

    See module docstring for reasoning-mode / cache-control rules.
    """
    from backend.modules.llm._adapters._anthropic_cache import (
        compute_cache_markers,
        is_anthropic_model,
    )

    cc_by_index: dict[int, dict] = {}
    if (
        request.anthropic_cache_ttl != "off"
        and is_anthropic_model(request.model)
    ):
        for marker in compute_cache_markers(
            request.messages, request.anthropic_cache_ttl,
        ):
            cc_by_index[marker.message_index] = _to_cache_control(marker.ttl)

    payload: dict = {
        "model": upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            _translate_message(m, cache_control=cc_by_index.get(i))
            for i, m in enumerate(request.messages)
        ],
    }
    if send_reasoning_flag:
        payload["reasoning"] = {"enabled": reasoning_enabled}
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload


def _to_cache_control(ttl: str) -> dict:
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}
```

- [ ] **Step 5: Run new tests to verify they pass**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache_emission_nano_gpt.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Run pre-existing nano-gpt tests for regressions**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_anthropic_cache_emission_nano_gpt.py
git commit -m "Emit Anthropic cache_control markers from nano-gpt adapter"
```

### Task 11: Observability log lines

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py` (StreamDone handler)
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py` (StreamDone handler)

- [ ] **Step 1: Locate the usage handler in OpenRouter**

The terminal `usage`-only chunk path lives in `_chunk_to_events` (around line 191-200). The cache fields appear on `usage`. We log on the adapter side, where we still have `request.model` and `request.anthropic_cache_ttl` in scope — which means at the point where `StreamDone` is emitted from the SSE loop. Adding the log inside `_chunk_to_events` would not have access to the request; instead, log in the streaming loop right after a `StreamDone` is yielded but before returning.

Cleanest spot: capture the raw usage dict alongside `StreamDone`. Add an explicit log line in the SSE loop at the moment the terminal usage chunk arrives:

In `stream_completion` of `_openrouter_http.py`, immediately after the SSE-decoded chunk produces a `StreamDone` (look for `if isinstance(event, StreamDone): seen_done = True` around line 519-520), inject the log. Gate on `is_anthropic_model` so the line never fires for GPT / Llama / etc. — keeps `grep anthropic_cache` precise.

```python
                                    for event in _chunk_to_events(parsed, acc):
                                        if isinstance(event, StreamDone):
                                            seen_done = True
                                            if is_anthropic_model(request.model):
                                                usage = parsed.get("usage") or {}
                                                _log.info(
                                                    "anthropic_cache adapter=openrouter "
                                                    "model=%s ttl=%s "
                                                    "cache_read=%d cache_creation=%d "
                                                    "input=%d",
                                                    payload.get("model"),
                                                    request.anthropic_cache_ttl,
                                                    usage.get("cache_read_input_tokens", 0),
                                                    usage.get("cache_creation_input_tokens", 0),
                                                    usage.get("prompt_tokens", 0),
                                                )
                                        yield event
                                        if isinstance(event, (StreamDone,
                                                               StreamRefused,
                                                               StreamError)):
                                            return
```

Add the import at the top of `_openrouter_http.py` (next to the other `_adapters._` imports):

```python
from backend.modules.llm._adapters._anthropic_cache import is_anthropic_model
```

- [ ] **Step 2: Mirror in `_nano_gpt_http.py`**

Same shape, around the analogous SSE loop block. Use `adapter=nano-gpt` in the prefix, `upstream_slug` for the model field (fine for grep), and gate on `is_anthropic_model(request.model)` so non-Claude completions stay quiet:

```python
                                    for event in _chunk_to_events(parsed, acc):
                                        if isinstance(event, StreamDone):
                                            seen_done = True
                                            if is_anthropic_model(request.model):
                                                usage = parsed.get("usage") or {}
                                                _log.info(
                                                    "anthropic_cache adapter=nano-gpt "
                                                    "model=%s ttl=%s "
                                                    "cache_read=%d cache_creation=%d "
                                                    "input=%d",
                                                    upstream_slug,
                                                    request.anthropic_cache_ttl,
                                                    usage.get("cache_read_input_tokens", 0),
                                                    usage.get("cache_creation_input_tokens", 0),
                                                    usage.get("prompt_tokens", 0),
                                                )
                                        yield event
                                        if isinstance(event, (StreamDone,
                                                               StreamRefused,
                                                               StreamError)):
                                            return
```

Add the import at the top of `_nano_gpt_http.py` next to the other `_adapters._` imports:

```python
from backend.modules.llm._adapters._anthropic_cache import is_anthropic_model
```

- [ ] **Step 3: Build verification**

```bash
uv run python -m py_compile \
    backend/modules/llm/_adapters/_openrouter_http.py \
    backend/modules/llm/_adapters/_nano_gpt_http.py
```

Expected: clean.

- [ ] **Step 4: Run all adapter tests one more time to confirm no regressions**

```bash
PYTHONPATH=$(pwd) uv run pytest backend/tests/modules/llm/adapters -v
```

Expected: pass (per memory `feedback_retry_test_brittleness.md` — if any retry/429 test flakes, retry once before declaring failure).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/modules/llm/_adapters/_nano_gpt_http.py
git commit -m "Log anthropic_cache usage on stream completion"
```

---

## Phase G — Frontend

### Task 12: TypeScript persona types

**Files:**
- Modify: `frontend/src/core/types/persona.ts`

- [ ] **Step 1: Add field to `PersonaDto`, `CreatePersonaRequest`, `UpdatePersonaRequest`**

After `reasoning_enabled` in each interface, add:

For `PersonaDto`:
```typescript
  // Anthropic prompt-cache TTL — only meaningful when the persona's
  // model is a Claude family member behind OR or nano-gpt. Frontend
  // hides the control unless the selected model passes
  // ``isAnthropicModel``. Default ``"off"`` keeps pre-existing
  // persona documents readable.
  anthropic_cache_ttl: 'off' | '5m' | '1h';
```

For `CreatePersonaRequest`:
```typescript
  anthropic_cache_ttl?: 'off' | '5m' | '1h';
```

For `UpdatePersonaRequest`:
```typescript
  anthropic_cache_ttl?: 'off' | '5m' | '1h';
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean (or unrelated pre-existing errors that are not on the touched file).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/types/persona.ts
git commit -m "Add anthropic_cache_ttl field to TS persona types"
```

### Task 13: TypeScript `isAnthropicModel` helper (TDD)

**Files:**
- Create: `frontend/src/features/llm/anthropicCache.ts`
- Create: `frontend/src/features/llm/__tests__/anthropicCache.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/llm/__tests__/anthropicCache.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'

import { isAnthropicModel } from '../anthropicCache'

describe('isAnthropicModel', () => {
  it.each([
    'anthropic/claude-3-7-sonnet-20250219',
    '~anthropic/claude-opus-4-1',
    'claude-haiku-4-5',
    'claude-3-7-sonnet-20250219',
    'anthropic/claude-3.5-sonnet-vision',
    'ANTHROPIC/Claude-Sonnet-4-5',
  ])('matches %s', (slug) => {
    expect(isAnthropicModel(slug)).toBe(true)
  })

  it.each([
    'openai/gpt-4',
    'openai/gpt-4o',
    'meta/llama-3.3-70b',
    'mistral-large-latest',
    'anthropic/claude-instant-1',
    'meta/llama-claude-skin',
    '',
    'anthropic/',
    'claude',
  ])('does not match %s', (slug) => {
    expect(isAnthropicModel(slug)).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd frontend && pnpm vitest run src/features/llm/__tests__/anthropicCache.test.ts
```

Expected: failure — module does not exist.

- [ ] **Step 3: Create the helper**

Create `frontend/src/features/llm/anthropicCache.ts`:

```typescript
/**
 * Mirror of backend ``is_anthropic_model``.
 *
 * Used by the persona-edit form to conditionally render the prompt-cache
 * dropdown. Must stay in lock-step with
 * ``backend/modules/llm/_adapters/_anthropic_cache.py``.
 *
 * Strategy: take everything after the last ``/`` (or the whole string
 * if there is no ``/``), then test for ``claude.*haiku|sonnet|opus``.
 */
const CLAUDE_RE = /claude.*\b(haiku|sonnet|opus)\b/i

export function isAnthropicModel(modelId: string): boolean {
  const tail = modelId.split('/').pop() ?? ''
  return CLAUDE_RE.test(tail)
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/features/llm/__tests__/anthropicCache.test.ts
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/llm/anthropicCache.ts \
        frontend/src/features/llm/__tests__/anthropicCache.test.ts
git commit -m "Add isAnthropicModel TS helper mirroring backend regex"
```

### Task 14: Persona EditTab dropdown

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`

- [ ] **Step 1: Read EditTab structure for the model picker and surrounding state**

```bash
grep -n "modelUniqueId\|ModelPicker\|temperature\|state\b" frontend/src/app/components/persona-overlay/EditTab.tsx | head -30
```

Note the line numbers for: state declarations (~30-50), the dirty-check (~135-145), the save payload (~180-190), and the JSX render of the temperature row (~430-440).

- [ ] **Step 2: Add state and a `useId` for the new control**

Near the existing state declarations (around lines 30-67), add:

```typescript
  const [anthropicCacheTtl, setAnthropicCacheTtl] = useState<'off' | '5m' | '1h'>(
    persona.anthropic_cache_ttl ?? 'off',
  )
  const cacheTtlId = useId()
```

- [ ] **Step 3: Include in the dirty-check**

Find the existing dirty-check expression (around line 136-142) and add a clause:

```typescript
  const isDirty =
    /* …existing clauses… */ ||
    anthropicCacheTtl !== (persona.anthropic_cache_ttl ?? 'off')
```

- [ ] **Step 4: Include in the save payload**

In the save handler (around line 180-190), include the new field. Mirror the existing pattern (e.g. `temperature`, `reasoning_enabled`):

```typescript
      const updateBody: UpdatePersonaRequest = {
        /* …existing fields… */
        anthropic_cache_ttl: anthropicCacheTtl,
      }
```

- [ ] **Step 5: Render the dropdown conditionally**

Place the new control directly under the model picker. Suggested placement: above the temperature row. The label uses the chakra-styled small-uppercase pattern already in the file.

```tsx
{isAnthropicModel(modelUniqueId ?? '') && (
  <div className="flex flex-col gap-1">
    <label
      htmlFor={cacheTtlId}
      className="text-[11px] text-white/40 uppercase tracking-wider"
    >
      Prompt cache
    </label>
    <select
      id={cacheTtlId}
      value={anthropicCacheTtl}
      onChange={(e) =>
        setAnthropicCacheTtl(e.target.value as 'off' | '5m' | '1h')
      }
      className="bg-[#0f0d16] text-white/85 border border-white/10 rounded px-2 py-1 text-[13px]"
    >
      <option value="off" style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}>
        Off
      </option>
      <option value="5m" style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}>
        5 minutes
      </option>
      <option value="1h" style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}>
        1 hour
      </option>
    </select>
    <p className="text-[11px] text-white/40">
      Reduces input cost on repeated context. Off by default.
    </p>
  </div>
)}
```

(The inline `style={{ background, color }}` on each `<option>` mirrors
CLAUDE.md "Frontend styling gotchas — Native `<select>` dropdowns".)

- [ ] **Step 6: Add the import at the top of EditTab.tsx**

```typescript
import { isAnthropicModel } from '../../../features/llm/anthropicCache'
```

(Adjust relative path to match the file's existing import style — check
sibling imports in the same file. If `@/features/...` aliases are in
use, prefer that.)

- [ ] **Step 7: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean (or only unrelated pre-existing errors).

- [ ] **Step 8: Run frontend tests**

```bash
cd frontend && pnpm vitest run
```

Expected: pass.

- [ ] **Step 9: Run the actual production build**

Per memory `feedback_frontend_build_check.md` — `tsc -b` (in `pnpm run build`) catches stricter errors than `tsc --noEmit`:

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Add Anthropic prompt-cache dropdown to persona EditTab"
```

---

## Phase H — End-to-End Verification

### Task 15: Manual verification on real device

**Goal:** Confirm the feature behaves correctly with real OR / nano-gpt traffic against actual Claude models. Per CLAUDE.md, build verification ≠ feature verification.

- [ ] **Step 1: Backend type / compile check**

```bash
uv run python -m py_compile \
    backend/modules/llm/_adapters/_anthropic_cache.py \
    backend/modules/llm/_adapters/_openrouter_http.py \
    backend/modules/llm/_adapters/_nano_gpt_http.py \
    backend/modules/chat/_orchestrator.py \
    backend/modules/chat/_handlers_ws.py \
    backend/modules/persona/_models.py \
    backend/modules/persona/_repository.py \
    backend/modules/persona/_handlers.py \
    shared/dtos/inference.py \
    shared/dtos/persona.py
```

Expected: no output.

- [ ] **Step 2: Backend tests (host, scoped — no DB needed)**

The strategy lib and adapter emission tests are pure-function /
HTTP-mocked, so they need no MongoDB. Scope the test run to the
relevant modules:

```bash
PYTHONPATH=$(pwd) uv run pytest \
    backend/tests/modules/llm/adapters \
    backend/tests/modules/persona \
    -v
```

Per memory `feedback_db_tests_on_host.md` — do **not** invoke the
live-DB tests (`backend/tests/integration/`,
`backend/tests/ws/test_sidecar_router.py`) on host; they require
the docker-compose MongoDB replica set.

Expected: all pass.

- [ ] **Step 3: Frontend production build**

```bash
cd frontend && pnpm run build
```

Expected: clean build, no TS errors.

- [ ] **Step 4: Manual verification — happy path 5m**

1. Boot the dev environment as usual.
2. Pick or create a persona pointing at `anthropic/claude-sonnet-4.5` via an OpenRouter connection.
3. Open EditTab — confirm the **Prompt cache** dropdown is visible directly under the model picker.
4. Set TTL to `5 minutes`. Save.
5. Open a fresh chat with the persona. Send 4 turns of normal back-and-forth.
6. Open the backend log and grep:

   ```bash
   grep "anthropic_cache" logs/backend.log | tail -20
   ```

7. Confirm:
   - Turn 1: `cache_read=0`, `cache_creation` > 0 (initial write of system + initial state).
   - Turn 2 onwards: `cache_read` > 0 and growing, `cache_creation` small (delta only).

- [ ] **Step 5: Manual verification — 1h block-boundary path**

1. Same persona, set TTL to `1 hour`. Save.
2. Send 9+ turns to cross the first block boundary (`BLOCK_SIZE = 8`).
3. Pause ~10 minutes (longer than the 5m TTL on the rolling tail, shorter than the 1h on the block).
4. Send another message.
5. Grep `anthropic_cache` for the post-pause turn.
6. Confirm: `cache_read` is high (block survived) but smaller than full prefix (recent tail had to be re-paid). `cache_creation` reflects the new tail-write.

- [ ] **Step 6: Manual verification — nano-gpt parity**

1. Switch the persona's model to a Claude model on a nano-gpt connection (e.g. `claude-3-7-sonnet-20250219`).
2. Repeat steps 4-5.
3. Confirm `adapter=nano-gpt` log lines appear with comparable cache hit / write behaviour.

- [ ] **Step 7: Manual verification — non-Anthropic dismissal**

1. Switch persona to `openai/gpt-4o` via OpenRouter.
2. Open EditTab — confirm the **Prompt cache** dropdown is **not visible**.
3. Send a message.
4. Grep `anthropic_cache` — confirm **no log lines appear** for the GPT-4o turn. The log emission is gated on `is_anthropic_model(request.model)` (Task 11), so non-Claude models stay quiet.

- [ ] **Step 8: Manual verification — backwards compatibility**

1. Open an old persona created **before** this change. Confirm:
   - EditTab loads cleanly.
   - If the persona uses a Claude model, dropdown shows `Off` (default).
   - Existing chat sessions with that persona continue to work without cache markers.

- [ ] **Step 9: Final commit covering anything left over**

If any incidental fix-ups were needed during manual verification (test tweaks, log-line phrasing), commit them now.

```bash
git status
# review and commit any remaining changes
```

- [ ] **Step 10: Push the feature branch**

```bash
git push -u origin feat/anthropic-cache-breakpoints
```

(Do **not** merge to master from a subagent — per memory `feedback_subagent_no_merge.md`. Merge happens explicitly at the user's signal in the main session, per CLAUDE.md "always merge to master after implementation" defaults.)

---

## Out of Scope (Future Work)

Tracked in spec §11; do **not** implement now:

- Tools / tool-definition cache_control
- 4th breakpoint usage (reserved)
- Block-size tuning (data-driven, after observability accumulates)
- Pre-heat on conversation load
- OpenAI-compat-SSE refactor that would centralise the duplicated marker emission between OR and nano-gpt — tracked separately in memory `project_openai_compat_refactor.md`
