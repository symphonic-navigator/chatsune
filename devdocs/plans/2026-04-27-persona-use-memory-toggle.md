# Persona "Use Memory" Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-persona `use_memory` toggle (default on) that gates memory-block injection in the chat prompt assembler while leaving memory generation, journals, about-me, and every other prompt layer unchanged.

**Architecture:** New `bool` field on the persona document and DTOs (Pydantic default `True` covers existing rows — no migration). The chat prompt assembler reads the already-loaded `persona_doc` and skips the `<memory>` block when the flag is false. Frontend adds one `<Toggle>` to the persona Edit tab below the existing NSFW toggle and round-trips the field through the existing persona create / update REST surface.

**Tech Stack:** Python 3.12 + Pydantic v2, FastAPI, MongoDB document store, React + TypeScript (Vite), Tailwind / inline styles.

**Spec:** `devdocs/specs/2026-04-27-persona-use-memory-toggle-design.md`

---

## File Structure

**Backend (modify):**
- `backend/modules/persona/_models.py` — add field to `PersonaDocument`
- `shared/dtos/persona.py` — add field to `PersonaDto`, `CreatePersonaDto`, `UpdatePersonaDto`
- `backend/modules/persona/_repository.py` — `create()` signature, doc dict, `to_dto()`
- `backend/modules/persona/_handlers.py` — `create_persona` passes `body.use_memory`
- `backend/modules/persona/_clone.py` — propagate during persona clone
- `backend/modules/persona/_export.py` — include in exported personality fields
- `backend/modules/persona/_import.py` — read on import (default `True`)
- `backend/modules/chat/_prompt_assembler.py` — gate `get_memory_context` call

**Backend (create):**
- `tests/modules/persona/test_use_memory_field.py` — DTO + repository round-trip
- (extend) `tests/test_prompt_assembler.py` — gate behaviour

**Frontend (modify):**
- `frontend/src/core/types/persona.ts` — add field to all three persona types
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — `DEFAULT_PERSONA.use_memory = true`
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — state, dirty check, save payload, new `<Toggle>`

---

## Task 1: Add `use_memory` to backend Pydantic models

**Files:**
- Modify: `backend/modules/persona/_models.py:19`
- Modify: `shared/dtos/persona.py` (PersonaDto, CreatePersonaDto, UpdatePersonaDto)
- Create: `tests/modules/persona/test_use_memory_field.py`

- [ ] **Step 1: Write the failing tests**

`tests/modules/persona/test_use_memory_field.py`:

```python
from datetime import UTC, datetime

from backend.modules.persona._models import PersonaDocument
from shared.dtos.persona import CreatePersonaDto, PersonaDto, UpdatePersonaDto


def _persona_doc_payload(**overrides) -> dict:
    base = {
        "_id": "p-1",
        "user_id": "u-1",
        "name": "Aria",
        "tagline": "Your helpful companion",
        "system_prompt": "You are helpful.",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "nsfw": False,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "AR",
        "pinned": False,
        "profile_image": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return base


def test_persona_document_defaults_use_memory_to_true():
    doc = PersonaDocument(**_persona_doc_payload())
    assert doc.use_memory is True


def test_persona_document_round_trips_use_memory_false():
    doc = PersonaDocument(**_persona_doc_payload(use_memory=False))
    assert doc.use_memory is False


def test_persona_dto_defaults_use_memory_to_true():
    dto = PersonaDto(
        id="p-1",
        user_id="u-1",
        name="Aria",
        tagline="Your helpful companion",
        system_prompt="You are helpful.",
        temperature=0.8,
        reasoning_enabled=False,
        nsfw=False,
        colour_scheme="solar",
        display_order=0,
        monogram="AR",
        pinned=False,
        profile_image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert dto.use_memory is True


def test_create_persona_dto_defaults_use_memory_to_true():
    dto = CreatePersonaDto(
        name="Aria",
        tagline="t",
        model_unique_id="ollama_cloud:llama3.2",
        system_prompt="p",
    )
    assert dto.use_memory is True


def test_create_persona_dto_accepts_use_memory_false():
    dto = CreatePersonaDto(
        name="Aria",
        tagline="t",
        model_unique_id="ollama_cloud:llama3.2",
        system_prompt="p",
        use_memory=False,
    )
    assert dto.use_memory is False


def test_update_persona_dto_use_memory_optional_default_none():
    dto = UpdatePersonaDto()
    assert dto.use_memory is None
    assert "use_memory" not in dto.model_dump(exclude_none=True)


def test_update_persona_dto_use_memory_round_trips_explicit_false():
    dto = UpdatePersonaDto(use_memory=False)
    assert dto.use_memory is False
    assert dto.model_dump(exclude_none=True)["use_memory"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/modules/persona/test_use_memory_field.py -v`
Expected: FAIL — every test errors with `AttributeError`/`ValidationError` because `use_memory` is not on the models yet.

- [ ] **Step 3: Add `use_memory` to `PersonaDocument`**

Edit `backend/modules/persona/_models.py`. Add after the existing `nsfw: bool` line (currently line 19):

```python
    nsfw: bool
    use_memory: bool = True
```

- [ ] **Step 4: Add `use_memory` to the three persona DTOs**

Edit `shared/dtos/persona.py`. In `PersonaDto`, after `nsfw: bool` (currently line 68):

```python
    nsfw: bool
    use_memory: bool = True
```

In `CreatePersonaDto`, after `nsfw: bool = False` (currently line 98):

```python
    nsfw: bool = False
    use_memory: bool = True
```

In `UpdatePersonaDto`, after `nsfw: bool | None = None` (currently line 120):

```python
    nsfw: bool | None = None
    use_memory: bool | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/modules/persona/test_use_memory_field.py -v`
Expected: PASS — all seven tests green.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/persona/_models.py shared/dtos/persona.py tests/modules/persona/test_use_memory_field.py
git commit -m "Add use_memory field to persona document and DTOs"
```

---

## Task 2: Persist `use_memory` through the persona repository

**Files:**
- Modify: `backend/modules/persona/_repository.py:19-58` (`create`)
- Modify: `backend/modules/persona/_repository.py:155-184` (`to_dto`)
- Modify: `tests/modules/persona/test_use_memory_field.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/modules/persona/test_use_memory_field.py`:

```python
from backend.modules.persona._repository import PersonaRepository


def _doc_with_memory_flag(value: bool | None) -> dict:
    base = _persona_doc_payload()
    if value is None:
        # legacy document — field absent entirely
        base.pop("use_memory", None)
    else:
        base["use_memory"] = value
    return base


def test_to_dto_defaults_missing_use_memory_to_true():
    dto = PersonaRepository.to_dto(_doc_with_memory_flag(None))
    assert dto.use_memory is True


def test_to_dto_preserves_explicit_false_use_memory():
    dto = PersonaRepository.to_dto(_doc_with_memory_flag(False))
    assert dto.use_memory is False


def test_to_dto_preserves_explicit_true_use_memory():
    dto = PersonaRepository.to_dto(_doc_with_memory_flag(True))
    assert dto.use_memory is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/modules/persona/test_use_memory_field.py::test_to_dto_defaults_missing_use_memory_to_true tests/modules/persona/test_use_memory_field.py::test_to_dto_preserves_explicit_false_use_memory tests/modules/persona/test_use_memory_field.py::test_to_dto_preserves_explicit_true_use_memory -v`
Expected: FAIL — `to_dto` raises `ValidationError` because it does not pass `use_memory`.

Note: the document model now requires the test-payload helper to also need adjustment — `_persona_doc_payload` calls `PersonaDocument` indirectly via `to_dto`. The dict-shape used in tests already matches MongoDB's raw form (no `use_memory` → default).

- [ ] **Step 3: Wire `use_memory` through `PersonaRepository.create`**

Edit `backend/modules/persona/_repository.py`. In the `create` signature (currently line 19-35), add a new parameter after `vision_fallback_model`:

```python
        vision_fallback_model: str | None = None,
        use_memory: bool = True,
    ) -> dict:
```

In the `doc = {...}` dict (currently line 36-56), add a new line after `"vision_fallback_model"`:

```python
            "vision_fallback_model": vision_fallback_model,
            "use_memory": use_memory,
            "nsfw": nsfw,
```

In `PersonaRepository.to_dto` (currently around line 155-184), add `use_memory=doc.get("use_memory", True)` after the `nsfw` line:

```python
            nsfw=doc.get("nsfw", False),
            use_memory=doc.get("use_memory", True),
            colour_scheme=doc["colour_scheme"],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/modules/persona/test_use_memory_field.py -v`
Expected: PASS — all ten tests green (the original seven plus the three new repository tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/persona/_repository.py tests/modules/persona/test_use_memory_field.py
git commit -m "Persist use_memory through persona repository"
```

---

## Task 3: Wire `use_memory` through the create handler

**Files:**
- Modify: `backend/modules/persona/_handlers.py:140-153` (`create_persona`)

The update path (`PATCH /api/personas/{id}`) needs no change — `update_persona` already does `body.model_dump(exclude_none=True)` which now correctly includes `use_memory` whenever the client sends `true` or `false`.

- [ ] **Step 1: Update `create_persona` to forward `use_memory`**

Edit `backend/modules/persona/_handlers.py`. In the `repo.create(...)` call (currently line 140-153), add a line after `vision_fallback_model`:

```python
        vision_fallback_model=body.vision_fallback_model,
        use_memory=body.use_memory,
    )
```

- [ ] **Step 2: Verify create + update integration paths still type-check**

Run: `uv run python -m py_compile backend/modules/persona/_handlers.py backend/modules/persona/_repository.py`
Expected: no output (clean compile).

Run: `uv run pytest tests/modules/persona/test_use_memory_field.py -v`
Expected: PASS — still ten tests green.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/persona/_handlers.py
git commit -m "Forward use_memory from create-persona handler"
```

---

## Task 4: Propagate `use_memory` through clone, export, and import

**Files:**
- Modify: `backend/modules/persona/_clone.py:77`
- Modify: `backend/modules/persona/_export.py:47`
- Modify: `backend/modules/persona/_import.py:299`

These three sites mirror the pattern already used for `nsfw`. Without this task, cloning or exporting and re-importing a persona would silently reset the toggle to its default.

- [ ] **Step 1: Read the existing nsfw lines for context**

Run: `grep -n "nsfw" backend/modules/persona/_clone.py backend/modules/persona/_export.py backend/modules/persona/_import.py`
Expected output:
```
backend/modules/persona/_clone.py:77:            nsfw=source.get("nsfw", False),
backend/modules/persona/_export.py:47:    "nsfw",
backend/modules/persona/_import.py:299:            nsfw=bool(personality.get("nsfw", False)),
```

- [ ] **Step 2: Patch `_clone.py`**

Edit `backend/modules/persona/_clone.py` line 77 area. Add a new line after the `nsfw=` line:

```python
            nsfw=source.get("nsfw", False),
            use_memory=source.get("use_memory", True),
```

- [ ] **Step 3: Patch `_export.py`**

Edit `backend/modules/persona/_export.py` line 47 area. The file has a list of personality field names to export — add `"use_memory"` after `"nsfw"`:

```python
    "nsfw",
    "use_memory",
```

- [ ] **Step 4: Patch `_import.py`**

Edit `backend/modules/persona/_import.py` line 299 area. Add a new line after the `nsfw=` line:

```python
            nsfw=bool(personality.get("nsfw", False)),
            use_memory=bool(personality.get("use_memory", True)),
```

- [ ] **Step 5: Verify everything still compiles**

Run: `uv run python -m py_compile backend/modules/persona/_clone.py backend/modules/persona/_export.py backend/modules/persona/_import.py`
Expected: no output (clean compile).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/persona/_clone.py backend/modules/persona/_export.py backend/modules/persona/_import.py
git commit -m "Propagate use_memory through clone, export, and import"
```

---

## Task 5: Gate memory injection in the chat prompt assembler

**Files:**
- Modify: `backend/modules/chat/_prompt_assembler.py:108-112`
- Modify: `tests/test_prompt_assembler.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prompt_assembler.py`:

```python
async def test_assemble_skips_memory_when_use_memory_false():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"soft_cot_enabled": False, "use_memory": False}), \
         patch("backend.modules.memory.get_memory_context", new_callable=AsyncMock) as mock_get_memory, \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value="I am Chris"):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    # The memory loader is never called when injection is disabled.
    mock_get_memory.assert_not_called()
    # No memory block in the assembled prompt.
    assert "<memory" not in result
    # About-me is unaffected.
    assert "I am Chris" in result
    assert '<userinfo priority="low">' in result


async def test_assemble_injects_memory_when_use_memory_true():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"soft_cot_enabled": False, "use_memory": True}), \
         patch("backend.modules.memory.get_memory_context", new_callable=AsyncMock, return_value="<memory>stuff</memory>") as mock_get_memory, \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    mock_get_memory.assert_awaited_once_with("user-1", "p-1")
    assert "<memory>stuff</memory>" in result


async def test_assemble_defaults_to_injecting_memory_for_legacy_persona_doc():
    """A persona doc that pre-dates the toggle has no use_memory key — must default to true."""
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"soft_cot_enabled": False}), \
         patch("backend.modules.memory.get_memory_context", new_callable=AsyncMock, return_value="<memory>legacy</memory>") as mock_get_memory, \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    mock_get_memory.assert_awaited_once()
    assert "<memory>legacy</memory>" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompt_assembler.py::test_assemble_skips_memory_when_use_memory_false tests/test_prompt_assembler.py::test_assemble_injects_memory_when_use_memory_true tests/test_prompt_assembler.py::test_assemble_defaults_to_injecting_memory_for_legacy_persona_doc -v`
Expected: FAIL — the "skips memory" test fails because today the assembler always calls `get_memory_context` and the mock records a call; the other two may pass already by coincidence (no harm — they pin behaviour we care about).

- [ ] **Step 3: Add the gate in `_prompt_assembler.py`**

Edit `backend/modules/chat/_prompt_assembler.py`. Replace the current memory-layer block (lines 108-112):

```python
    # Layer: User memory (if available)
    from backend.modules.memory import get_memory_context
    memory_xml = await get_memory_context(user_id, persona_id) if persona_id else None
    if memory_xml:
        parts.append(memory_xml)
```

with:

```python
    # Layer: User memory (if available, and the persona opts in to injection).
    # Generation jobs continue regardless — only the prompt-time read path
    # is gated. See devdocs/specs/2026-04-27-persona-use-memory-toggle-design.md.
    use_memory = bool(persona_doc.get("use_memory", True)) if persona_doc else True
    if persona_id and use_memory:
        from backend.modules.memory import get_memory_context
        memory_xml = await get_memory_context(user_id, persona_id)
        if memory_xml:
            parts.append(memory_xml)
```

- [ ] **Step 4: Run all assembler tests to verify they pass**

Run: `uv run pytest tests/test_prompt_assembler.py -v`
Expected: PASS — every test, including the three new ones and the four pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_prompt_assembler.py tests/test_prompt_assembler.py
git commit -m "Gate memory injection on persona use_memory flag"
```

---

## Task 6: Add `use_memory` to frontend persona types

**Files:**
- Modify: `frontend/src/core/types/persona.ts`

- [ ] **Step 1: Add to `PersonaDto`**

Edit `frontend/src/core/types/persona.ts`. After the `nsfw: boolean;` line (currently line 24):

```ts
  nsfw: boolean;
  use_memory: boolean;
```

- [ ] **Step 2: Add to `CreatePersonaRequest`**

In the same file, after `nsfw?: boolean;` (currently line 68):

```ts
  nsfw?: boolean;
  use_memory?: boolean;
```

- [ ] **Step 3: Add to `UpdatePersonaRequest`**

In the same file, after `nsfw?: boolean;` (currently line 84):

```ts
  nsfw?: boolean;
  use_memory?: boolean;
```

- [ ] **Step 4: Verify the frontend type-checks**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: PASS (no errors). Note: at this point any `PersonaDto` literal that does not provide `use_memory` will fail compilation. The next task fixes the only such literal (`DEFAULT_PERSONA` in `PersonaOverlay.tsx`).

If `pnpm tsc --noEmit` reports the missing `use_memory` on `DEFAULT_PERSONA`, that is expected — the task ordering means Task 7 will resolve it. Do not commit yet; proceed to Task 7 first.

- [ ] **Step 5: Hold off on commit**

Do not commit until Task 7's `DEFAULT_PERSONA` change is in. The two changes ship as a single coherent commit so that no intermediate state has a broken type-check.

---

## Task 7: Add `use_memory` toggle to the persona Edit tab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx:47-69` (`DEFAULT_PERSONA`)
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`

- [ ] **Step 1: Add `use_memory` to `DEFAULT_PERSONA`**

Edit `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`. In the `DEFAULT_PERSONA` literal, after `nsfw: false,` (currently line 58):

```ts
  nsfw: false,
  use_memory: true,
```

- [ ] **Step 2: Add `useMemory` state to `EditTab`**

Edit `frontend/src/app/components/persona-overlay/EditTab.tsx`. After the `nsfw` state (currently line 32):

```tsx
  const [nsfw, setNsfw] = useState(persona.nsfw)
  const [useMemory, setUseMemory] = useState(persona.use_memory)
```

- [ ] **Step 3: Extend the `isDirty` expression**

In the same file, in the `isDirty` chain (currently line 121-131), add `useMemory !== persona.use_memory ||` after the `nsfw !== persona.nsfw ||` line:

```tsx
    nsfw !== persona.nsfw ||
    useMemory !== persona.use_memory ||
    modelUniqueId !== persona.model_unique_id
```

- [ ] **Step 4: Add `use_memory` to the save payload**

In the same file, in `handleSave` (currently line 137-157), add a line after `nsfw,` (currently line 150):

```tsx
        nsfw,
        use_memory: useMemory,
        model_unique_id: modelUniqueId,
```

- [ ] **Step 5: Render the new `<Toggle>` directly below NSFW**

In the same file, after the existing NSFW `<Toggle>` block (currently line 467-473) and before the closing `</div>` of the toggles container (line 474), add:

```tsx
          <Toggle
            label="Use memory"
            description="Inject this persona's memories into the prompt. Memories are still generated when off."
            value={useMemory}
            onChange={setUseMemory}
            chakraHex={chakra.hex}
          />
```

- [ ] **Step 6: Run frontend build and full type-check**

Run: `cd frontend && pnpm run build`
Expected: PASS — clean build, no TypeScript errors. (Per project convention, `pnpm run build` is the canonical check; `tsc --noEmit` alone misses some stricter type errors that `tsc -b` catches.)

- [ ] **Step 7: Commit Tasks 6 + 7 together**

```bash
git add frontend/src/core/types/persona.ts \
        frontend/src/app/components/persona-overlay/PersonaOverlay.tsx \
        frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Add Use memory toggle to persona Edit tab"
```

---

## Task 8: End-to-end build verification and manual smoke test

**Files:** none modified — verification only.

- [ ] **Step 1: Backend syntax check across every touched file**

Run:
```bash
uv run python -m py_compile \
  backend/modules/persona/_models.py \
  backend/modules/persona/_repository.py \
  backend/modules/persona/_handlers.py \
  backend/modules/persona/_clone.py \
  backend/modules/persona/_export.py \
  backend/modules/persona/_import.py \
  backend/modules/chat/_prompt_assembler.py \
  shared/dtos/persona.py
```
Expected: no output (clean compile).

- [ ] **Step 2: Backend targeted test run**

Run:
```bash
uv run pytest \
  tests/modules/persona/test_use_memory_field.py \
  tests/test_prompt_assembler.py \
  -v
```
Expected: PASS — every test (the new ones and all pre-existing prompt-assembler tests) green.

Do **not** run the full backend suite on the host — four MongoDB-using files require Docker and are not part of this change's scope.

- [ ] **Step 3: Frontend build verification**

Run: `cd frontend && pnpm run build`
Expected: PASS — clean build with no TypeScript errors.

- [ ] **Step 4: Manual smoke test (browser, real backend)**

Bring up the dev stack as usual (`docker compose up -d` for the database, then run backend + Vite dev server). With a logged-in browser session:

1. **Default-on backwards compatibility.** Open an existing persona's Edit tab. The new "Use memory" toggle is rendered in the on-state.
2. **Toggle off.** Switch the toggle off and click Save. Re-open the persona — the toggle remains off (round-trip OK).
3. **Prompt content reflects the flag.** Send a message in a chat against this persona. Inspect the assembled system prompt (via the "Show prompt" diagnostic if available, or via backend logs) — there is no `<memory>` block. The `<userinfo>` block (about-me) is still present.
4. **Generation continues while off.** Send several substantive messages, then trigger or wait for the consolidation job. Open the Memories tab — new entries appear despite the toggle being off.
5. **Re-enabling picks up the backlog.** Toggle the switch back on, save, send the next message. The `<memory>` block reappears in the assembled prompt and contains the entries from step 4.
6. **About-me independence.** With the toggle off, change the user-level about-me text. The next message's prompt reflects the new about-me regardless of the toggle's state.
7. **New persona create.** Create a new persona via the overlay's create flow. The "Use memory" toggle starts in the on-state; the persisted document round-trips with `use_memory: true`.

- [ ] **Step 5: Commit (no-op if everything was already committed)**

If verification surfaces nothing to fix, this task has no commit. If a fix is needed, commit it with a focused message; do not amend prior commits.

---

## Out-of-scope reminders for the implementer

- Do **not** add a database migration script. The Pydantic default of `True` and `doc.get("use_memory", True)` calls are sufficient.
- Do **not** modify `assemble_preview` (the human-readable diagnostic preview); it does not include memory today and the spec keeps it that way.
- Do **not** touch the memory module — generation, consolidation, journals, embeddings all stay as-is.
- Do **not** rename or remove the existing `nsfw` toggle. Place the new toggle directly below it; both should remain visible.
- Do **not** merge to master, push to remote, or switch branches. Implementation only.
