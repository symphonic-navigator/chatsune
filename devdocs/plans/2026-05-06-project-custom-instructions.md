# Project Custom Instructions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-project Custom Instructions field that becomes a new layer in the assembled system prompt, sitting between model-instructions and the persona, so chats inside a project automatically inherit project-scoped behaviour shaping.

**Architecture:** New optional `system_prompt: str | None` on `ProjectDocument` / `ProjectDto`. The chat prompt assembler reads it on every inference call and emits a `<projectinstructions priority="high">` layer between model-instructions and persona. Frontend exposes the field as a save-on-blur textarea in the project overview tab.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + Motor (MongoDB), TypeScript + React + Vite + Tailwind, vitest, pytest. Spec: `devdocs/specs/2026-05-06-project-custom-instructions-design.md`.

---

## File Structure

**Backend — modify:**
- `backend/modules/project/_models.py` — add `system_prompt` to `ProjectDocument`
- `backend/modules/project/_repository.py` — extend `create()`, `to_dto()`; add `get_system_prompt()`
- `backend/modules/project/__init__.py` — export `get_system_prompt`
- `backend/modules/project/_handlers.py` — wire `system_prompt` through POST and PATCH
- `backend/modules/chat/_prompt_assembler.py` — new helper, signature, layer
- `backend/modules/chat/_orchestrator.py` — pass `project_id` to `assemble()`
- `shared/dtos/project.py` — add field to `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto`

**Backend — create:**
- (none — all changes extend existing files)

**Backend — test:**
- `tests/test_prompt_assembler.py` — extend with project-CI cases
- `tests/test_shared_project_contracts.py` — extend DTO tests
- `tests/test_project_handlers_mindspace.py` — extend with system_prompt PATCH cases (DB-bound; runs in Docker / CI)
- `tests/test_project_repository_system_prompt.py` — new file for repo-level `get_system_prompt` tests (DB-bound)

**Frontend — modify:**
- `frontend/src/features/projects/types.ts` — add `system_prompt` to `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto`
- `frontend/src/features/projects/tabs/ProjectOverviewTab.tsx` — new textarea section
- `frontend/src/features/projects/__tests__/ProjectOverviewTab.test.tsx` — extend tests

---

### Task 1: Add `system_prompt` to shared DTOs

**Files:**
- Modify: `shared/dtos/project.py`
- Test: `tests/test_shared_project_contracts.py` (existing file)

- [ ] **Step 1: Inspect current contracts test to learn the test idiom**

Run: `head -80 tests/test_shared_project_contracts.py`
Expected: shows existing assertions on `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto` shapes. Use the same idioms (direct constructor calls + assertions).

- [ ] **Step 2: Add a failing test for `system_prompt` round-trip on the three DTOs**

Append to `tests/test_shared_project_contracts.py`:

```python
from shared.dtos.project import (
    ProjectDto,
    ProjectCreateDto,
    ProjectUpdateDto,
    UNSET,
    _Unset,
)
from datetime import datetime


def test_project_dto_round_trips_system_prompt():
    now = datetime.now()
    dto = ProjectDto(
        id="p1",
        user_id="u1",
        title="t",
        emoji=None,
        description=None,
        nsfw=False,
        pinned=False,
        sort_order=0,
        knowledge_library_ids=[],
        system_prompt="be helpful",
        created_at=now,
        updated_at=now,
    )
    assert dto.system_prompt == "be helpful"


def test_project_dto_system_prompt_defaults_to_none():
    now = datetime.now()
    dto = ProjectDto(
        id="p1",
        user_id="u1",
        title="t",
        emoji=None,
        description=None,
        nsfw=False,
        pinned=False,
        sort_order=0,
        knowledge_library_ids=[],
        created_at=now,
        updated_at=now,
    )
    assert dto.system_prompt is None


def test_project_create_dto_accepts_system_prompt():
    dto = ProjectCreateDto(title="t", system_prompt="hi")
    assert dto.system_prompt == "hi"


def test_project_create_dto_system_prompt_defaults_to_none():
    dto = ProjectCreateDto(title="t")
    assert dto.system_prompt is None


def test_project_update_dto_system_prompt_uses_unset_sentinel():
    dto = ProjectUpdateDto()
    assert isinstance(dto.system_prompt, _Unset)


def test_project_update_dto_system_prompt_explicit_none_clears():
    dto = ProjectUpdateDto(system_prompt=None)
    assert dto.system_prompt is None
    assert not isinstance(dto.system_prompt, _Unset)


def test_project_update_dto_system_prompt_accepts_string():
    dto = ProjectUpdateDto(system_prompt="updated")
    assert dto.system_prompt == "updated"
```

- [ ] **Step 3: Run the new tests and confirm they fail**

Run from repo root: `PYTHONPATH=. uv run pytest tests/test_shared_project_contracts.py -v -k system_prompt`
Expected: FAIL — `ProjectDto` / `ProjectCreateDto` / `ProjectUpdateDto` do not have a `system_prompt` attribute yet.

- [ ] **Step 4: Add the field to all three DTOs**

In `shared/dtos/project.py`, modify `ProjectDto` to add (place after `knowledge_library_ids: list[str] = ...` and before `created_at`):

```python
    # Mindspace: optional per-project Custom Instructions injected into
    # the assembled system prompt between model-instructions and persona.
    # Defaults to None; legacy documents without the field deserialise
    # unchanged.
    system_prompt: str | None = None
```

Modify `ProjectCreateDto` to add (place after `knowledge_library_ids`):

```python
    system_prompt: str | None = None
```

Modify `ProjectUpdateDto` to add (place after the existing `knowledge_library_ids` field, mirroring its UNSET pattern):

```python
    system_prompt: str | None | _Unset = Field(default=UNSET)
```

- [ ] **Step 5: Run the tests again and confirm they pass**

Run: `PYTHONPATH=. uv run pytest tests/test_shared_project_contracts.py -v -k system_prompt`
Expected: PASS — all seven new tests green.

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/project.py tests/test_shared_project_contracts.py
git commit -m "Add system_prompt field to project DTOs"
```

---

### Task 2: Persist `system_prompt` through the project repository

**Files:**
- Modify: `backend/modules/project/_models.py`
- Modify: `backend/modules/project/_repository.py`
- Test: `tests/test_project_repository_system_prompt.py` (new, DB-bound)

- [ ] **Step 1: Add `system_prompt` to `ProjectDocument`**

Modify `backend/modules/project/_models.py` — add after `knowledge_library_ids` and before `created_at`:

```python
    # Mindspace: optional per-project Custom Instructions. ``None`` for
    # legacy documents that lack the field; backwards-compatible read.
    system_prompt: str | None = None
```

- [ ] **Step 2: Update repo `create()` signature and write path**

In `backend/modules/project/_repository.py`, change `create()` to accept `system_prompt`:

```python
    async def create(
        self,
        user_id: str,
        title: str,
        emoji: str | None,
        description: str | None,
        nsfw: bool,
        knowledge_library_ids: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> dict:
        now = datetime.now(UTC).replace(tzinfo=None)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "title": title,
            "emoji": emoji,
            "description": description,
            "nsfw": nsfw,
            "pinned": False,
            "sort_order": 0,
            "knowledge_library_ids": list(knowledge_library_ids or []),
            "system_prompt": system_prompt,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc
```

- [ ] **Step 3: Update `to_dto()` to surface the field**

In `backend/modules/project/_repository.py`, modify `to_dto`:

```python
    @staticmethod
    def to_dto(doc: dict) -> ProjectDto:
        return ProjectDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            title=doc["title"],
            emoji=doc.get("emoji"),
            description=doc.get("description"),
            nsfw=doc.get("nsfw", False),
            pinned=doc.get("pinned", False),
            sort_order=doc.get("sort_order", 0),
            knowledge_library_ids=list(doc.get("knowledge_library_ids", []) or []),
            # Mindspace: legacy documents lack the field; ``None`` default
            # round-trips cleanly into the DTO's nullable shape.
            system_prompt=doc.get("system_prompt"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

- [ ] **Step 4: Add `get_system_prompt()` projection method to the repo**

Append to `ProjectRepository` (after `get_library_ids`):

```python
    async def get_system_prompt(
        self, project_id: str, user_id: str,
    ) -> str | None:
        """Return the project's Custom Instructions or ``None``.

        Projection-only fetch — used by the chat orchestrator on every
        inference turn, mirroring ``get_library_ids``. Returns ``None``
        if the project does not exist, is not owned by ``user_id``, or
        has no CI set.
        """
        doc = await self._collection.find_one(
            {"_id": project_id, "user_id": user_id},
            projection={"system_prompt": 1},
        )
        if doc is None:
            return None
        return doc.get("system_prompt")
```

- [ ] **Step 5: Write a DB-bound test for the projection method**

Create `tests/test_project_repository_system_prompt.py`:

```python
"""Tests for ProjectRepository.get_system_prompt — projection-only fetch
of the per-project Custom Instructions added by Mindspace project-CI."""

import pytest_asyncio

from backend.modules.project import ProjectRepository


@pytest_asyncio.fixture
async def repo(client, db):
    """The ``client`` fixture wires up the app + clean DB; ``db`` gives
    us a Motor handle bound to the test database."""
    return ProjectRepository(db)


async def test_get_system_prompt_returns_value_for_owner(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
        system_prompt="be helpful",
    )
    result = await repo.get_system_prompt(proj["_id"], "u-a")
    assert result == "be helpful"


async def test_get_system_prompt_returns_none_for_missing(repo):
    result = await repo.get_system_prompt("does-not-exist", "u-a")
    assert result is None


async def test_get_system_prompt_returns_none_for_wrong_owner(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
        system_prompt="secret",
    )
    result = await repo.get_system_prompt(proj["_id"], "u-b")
    assert result is None


async def test_get_system_prompt_returns_none_when_unset(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
    )
    result = await repo.get_system_prompt(proj["_id"], "u-a")
    assert result is None


async def test_to_dto_round_trips_system_prompt(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
        system_prompt="round trip",
    )
    dto = ProjectRepository.to_dto(proj)
    assert dto.system_prompt == "round trip"
```

- [ ] **Step 6: Run repo tests via Docker (DB-bound)**

These tests need MongoDB; on the host they require Docker. Run from repo root:

```bash
docker compose run --rm backend uv run pytest tests/test_project_repository_system_prompt.py -v
```

Expected: PASS — all five tests green. If Docker is not running, the subagent must surface this in their final report; do not skip the assertion or weaken the tests to run on host without DB.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/project/_models.py backend/modules/project/_repository.py tests/test_project_repository_system_prompt.py
git commit -m "Persist system_prompt on projects via repository"
```

---

### Task 3: Expose `get_system_prompt` on the project module's public API

**Files:**
- Modify: `backend/modules/project/__init__.py`

- [ ] **Step 1: Add the exported helper**

In `backend/modules/project/__init__.py`, add this function (place near `get_library_ids`):

```python
async def get_system_prompt(project_id: str, user_id: str) -> str | None:
    """Return the project's Custom Instructions or ``None``.

    Returns ``None`` if the project does not exist, does not belong to
    the user, or has no CI set. Used by the chat prompt assembler on
    every inference turn — mirrors ``get_library_ids`` in shape and
    cost.
    """
    return await _repo().get_system_prompt(project_id, user_id)
```

- [ ] **Step 2: Add it to `__all__`**

Modify the `__all__` block in `backend/modules/project/__init__.py` to include the new symbol:

```python
__all__ = [
    "router",
    "init_indexes",
    "ProjectRepository",
    "delete_all_for_user",
    "get_library_ids",
    "get_system_prompt",
    "list_project_ids_for_user",
    "remove_library_from_all_projects",
    "set_pinned",
    "cascade_delete_project",
    "get_usage_counts",
]
```

- [ ] **Step 3: Sanity-check import via Python**

Run from repo root: `PYTHONPATH=. uv run python -c "from backend.modules.project import get_system_prompt; print(get_system_prompt)"`
Expected: prints `<function get_system_prompt at 0x...>` with no ImportError.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/project/__init__.py
git commit -m "Export get_system_prompt from the project module"
```

---

### Task 4: Wire `system_prompt` through the project HTTP handlers

**Files:**
- Modify: `backend/modules/project/_handlers.py`
- Test: `tests/test_project_handlers_mindspace.py` (existing, DB-bound)

- [ ] **Step 1: Wire `system_prompt` through `POST /api/projects`**

In `backend/modules/project/_handlers.py`, modify `create_project` to forward the field:

```python
@router.post("", status_code=201)
async def create_project(
    body: ProjectCreateDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    doc = await repo.create(
        user_id=user["sub"],
        title=body.title,
        emoji=body.emoji,
        description=body.description,
        nsfw=body.nsfw,
        knowledge_library_ids=body.knowledge_library_ids,
        system_prompt=body.system_prompt,
    )
    dto = ProjectRepository.to_dto(doc)
    await event_bus.publish(
        Topics.PROJECT_CREATED,
        ProjectCreatedEvent(
            project_id=doc["_id"],
            user_id=user["sub"],
            project=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return dto
```

- [ ] **Step 2: Wire `system_prompt` through `PATCH /api/projects/{id}` with the UNSET sentinel**

In the same file, modify `update_project` — add a sentinel-aware block alongside the existing description / emoji / knowledge_library_ids handling, before the `if not fields:` check:

```python
    # Sentinel-aware system_prompt handling: UNSET → don't touch;
    # None → clear; str → set. Mirrors the description / emoji pattern.
    if not isinstance(body.system_prompt, _Unset):
        fields["system_prompt"] = body.system_prompt
```

- [ ] **Step 3: Add HTTP-level tests for create + patch behaviour**

Append to `tests/test_project_handlers_mindspace.py`:

```python
# ---------------------------------------------------------------------------
# system_prompt — create + patch
# ---------------------------------------------------------------------------

async def test_create_accepts_system_prompt(
    client: AsyncClient, auth_user_id, db,
):
    resp = await client.post(
        "/api/projects",
        json={"title": "P", "system_prompt": "be helpful"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["system_prompt"] == "be helpful"


async def test_create_system_prompt_defaults_to_none(
    client: AsyncClient, auth_user_id, db,
):
    resp = await client.post("/api/projects", json={"title": "P"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["system_prompt"] is None


async def test_patch_sets_system_prompt(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description=None, nsfw=False,
    )
    resp = await client.patch(
        f"/api/projects/{proj['_id']}",
        json={"system_prompt": "new"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["system_prompt"] == "new"


async def test_patch_clears_system_prompt_with_explicit_null(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description=None, nsfw=False,
        system_prompt="initial",
    )
    resp = await client.patch(
        f"/api/projects/{proj['_id']}",
        json={"system_prompt": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["system_prompt"] is None


async def test_patch_omitting_system_prompt_leaves_value(
    client: AsyncClient, auth_user_id, db,
):
    repo = ProjectRepository(db)
    proj = await repo.create(
        user_id=auth_user_id, title="P",
        emoji=None, description=None, nsfw=False,
        system_prompt="keep me",
    )
    resp = await client.patch(
        f"/api/projects/{proj['_id']}",
        json={"title": "renamed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["system_prompt"] == "keep me"
    assert resp.json()["title"] == "renamed"
```

- [ ] **Step 4: Run the new handler tests via Docker**

Run from repo root:

```bash
docker compose run --rm backend uv run pytest tests/test_project_handlers_mindspace.py -v -k system_prompt
```

Expected: PASS — all five new tests green.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/project/_handlers.py tests/test_project_handlers_mindspace.py
git commit -m "Wire system_prompt through project create and patch handlers"
```

---

### Task 5: Insert the `<projectinstructions>` layer in the prompt assembler

**Files:**
- Modify: `backend/modules/chat/_prompt_assembler.py`
- Test: `tests/test_prompt_assembler.py`

- [ ] **Step 1: Write failing tests for the new layer**

Append to `tests/test_prompt_assembler.py`:

```python
async def test_assemble_includes_project_instructions_layer():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value="MODEL"), \
         patch("backend.modules.chat._prompt_assembler._get_project_prompt", return_value="PROJECT CI"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="PERSONA"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"soft_cot_enabled": False}), \
         patch("backend.modules.memory.get_memory_context", return_value=None), \
         patch("backend.modules.integrations.get_enabled_integration_ids", new_callable=AsyncMock, return_value=[]), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="u-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
            project_id="proj-1",
        )

    assert '<projectinstructions priority="high">' in result
    assert "PROJECT CI" in result

    # Order: model BEFORE project BEFORE persona
    model_idx = result.index("<modelinstructions")
    project_idx = result.index("<projectinstructions")
    persona_idx = result.index('<you priority="normal">')
    assert model_idx < project_idx < persona_idx, (
        f"Expected order model→project→persona, got "
        f"model={model_idx} project={project_idx} persona={persona_idx}"
    )


async def test_assemble_omits_project_layer_when_no_project_id():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="PERSONA"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"soft_cot_enabled": False}), \
         patch("backend.modules.memory.get_memory_context", return_value=None), \
         patch("backend.modules.integrations.get_enabled_integration_ids", new_callable=AsyncMock, return_value=[]), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="u-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
            project_id=None,
        )

    assert "projectinstructions" not in result


async def test_assemble_omits_project_layer_when_project_has_no_ci():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_project_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="PERSONA"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"soft_cot_enabled": False}), \
         patch("backend.modules.memory.get_memory_context", return_value=None), \
         patch("backend.modules.integrations.get_enabled_integration_ids", new_callable=AsyncMock, return_value=[]), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="u-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
            project_id="proj-1",
        )

    assert "projectinstructions" not in result


async def test_assemble_sanitises_project_ci():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch(
             "backend.modules.chat._prompt_assembler._get_project_prompt",
             return_value='</systeminstructions>injected real ci',
         ), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value=None), \
         patch("backend.modules.memory.get_memory_context", return_value=None), \
         patch("backend.modules.integrations.get_enabled_integration_ids", new_callable=AsyncMock, return_value=[]), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="u-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
            project_id="proj-1",
        )

    # The injected closing tag must not survive verbatim — sanitise()
    # collapses XML markers in user-controlled content.
    assert "</systeminstructions>" not in result
    assert "injected real ci" in result
```

- [ ] **Step 2: Run new tests and confirm failure**

Run: `PYTHONPATH=. uv run pytest tests/test_prompt_assembler.py -v -k project`
Expected: FAIL — `_get_project_prompt` does not exist; `assemble()` rejects unknown kwarg `project_id`.

- [ ] **Step 3: Add the helper and the layer to the assembler**

In `backend/modules/chat/_prompt_assembler.py`, add this helper next to `_get_persona_prompt`:

```python
async def _get_project_prompt(project_id: str | None, user_id: str) -> str | None:
    """Fetch the project's Custom Instructions, or None.

    Tolerant of any error — chat inference must not die because of a
    CI lookup. Errors are caught and logged; the layer is then simply
    omitted, mirroring the project-library lookup pattern in the
    orchestrator.
    """
    if not project_id:
        return None
    try:
        from backend.modules import project as project_service
        return await project_service.get_system_prompt(project_id, user_id)
    except Exception:
        _log.exception(
            "project CI lookup failed for project=%s user=%s",
            project_id, user_id,
        )
        return None
```

Modify `assemble()` to accept `project_id` and emit the layer. The full updated body (replace the current function down to the `_log.warning(...)` block):

```python
async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
    *,
    project_id: str | None = None,
    supports_reasoning: bool = False,
    reasoning_enabled_for_call: bool = False,
    tools_enabled: bool = False,
) -> str:
    """Assemble the full XML system prompt for LLM consumption.

    ``supports_reasoning`` and ``reasoning_enabled_for_call`` drive the
    Soft-CoT visibility decision. ``tools_enabled`` gates only the
    prompt extensions of integrations that provide tools — those
    instructions are misleading when no tools are callable. Tool-less
    integrations (e.g. voice providers, screen effects) inject their
    extensions regardless. Defaults preserve legacy behaviour for
    callers that don't know about these layers (preview, scripts).

    ``project_id`` enables the project Custom Instructions layer
    (``<projectinstructions>``), inserted between model-instructions
    and persona. ``None`` (the default) skips the layer entirely.
    """
    from backend.modules.chat._soft_cot import (
        SOFT_COT_INSTRUCTIONS,
        is_soft_cot_active,
    )

    admin_prompt = await _get_admin_prompt()
    model_instructions = await _get_model_instructions(user_id, model_unique_id)
    project_prompt = await _get_project_prompt(project_id, user_id)
    persona_prompt = await _get_persona_prompt(persona_id, user_id)
    persona_doc = await _get_persona_doc(persona_id, user_id)
    user_about_me = await _get_user_about_me(user_id)

    parts: list[str] = []

    # Layer 1: Admin — trusted, NOT sanitised
    if admin_prompt and admin_prompt.strip():
        parts.append(
            f'<systeminstructions priority="highest">\n{admin_prompt.strip()}\n</systeminstructions>'
        )

    # Layer 2: Model instructions — user-controlled, sanitised
    if model_instructions and model_instructions.strip():
        cleaned = sanitise(model_instructions.strip())
        if cleaned:
            parts.append(
                f'<modelinstructions priority="high">\n{cleaned}\n</modelinstructions>'
            )

    # Layer 3: Project Custom Instructions — user-controlled, sanitised.
    # Sits between model-instructions and persona so project-level scope
    # brackets the persona's voice. Layer is omitted entirely when no
    # project is bound to the session, or when the project has no CI.
    if project_prompt and project_prompt.strip():
        cleaned = sanitise(project_prompt.strip())
        if cleaned:
            parts.append(
                f'<projectinstructions priority="high">\n{cleaned}\n</projectinstructions>'
            )

    # Layer 4: Persona — user-controlled, sanitised
    if persona_prompt and persona_prompt.strip():
        cleaned = sanitise(persona_prompt.strip())
        if cleaned:
            parts.append(f'<you priority="normal">\n{cleaned}\n</you>')

    # Soft-CoT instruction block — sits between persona and memory so it
    # is "felt" alongside the persona voice but does not displace admin or
    # model instructions. Injected only when the persona has opted in and
    # native Hard-CoT is not taking over this inference call.
    soft_cot_enabled = bool(persona_doc and persona_doc.get("soft_cot_enabled"))
    if is_soft_cot_active(soft_cot_enabled, supports_reasoning, reasoning_enabled_for_call):
        parts.append(SOFT_COT_INSTRUCTIONS)

    # Layer: User memory (if available, and the persona opts in to injection).
    use_memory = bool(persona_doc.get("use_memory", True)) if persona_doc else True
    if persona_id and use_memory:
        from backend.modules.memory import get_memory_context
        memory_xml = await get_memory_context(user_id, persona_id)
        if memory_xml:
            parts.append(memory_xml)

    # Layer: Integration prompt extensions (active integrations for this persona).
    from backend.modules.integrations import get_integration_prompt_extensions
    extensions = await get_integration_prompt_extensions(
        user_id, persona_id, tools_enabled=tools_enabled,
    )
    if extensions:
        parts.append(extensions)

    if not tools_enabled:
        parts.append(
            '<toolavailability priority="high">\n'
            'You have no tools available in this conversation right now. '
            'Do not attempt to call any tool, and do not claim to have '
            'any — if asked about your tools, say they are disabled for '
            'this session.\n'
            '</toolavailability>'
        )

    # Layer 5: User about_me — user-controlled, sanitised
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

(Note: `assemble_preview` is **unchanged** — project CI does not appear in the persona-editor preview, per spec section 4.5 / 5.)

- [ ] **Step 4: Run new tests and confirm they pass**

Run: `PYTHONPATH=. uv run pytest tests/test_prompt_assembler.py -v -k project`
Expected: PASS — all four new tests green.

- [ ] **Step 5: Run the full assembler test module to confirm no regression**

Run: `PYTHONPATH=. uv run pytest tests/test_prompt_assembler.py -v`
Expected: PASS — all existing tests still green (the new `project_id` parameter has a default of `None` so existing call sites compile unchanged).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chat/_prompt_assembler.py tests/test_prompt_assembler.py
git commit -m "Add projectinstructions layer to the prompt assembler"
```

---

### Task 6: Pass the session's `project_id` from the chat orchestrator into `assemble()`

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Update the `assemble()` call site**

In `backend/modules/chat/_orchestrator.py`, around line 577, modify the `system_prompt = await assemble(...)` call to forward the session's `project_id`:

```python
    # Assemble system prompt
    tools_enabled_flag = session.get("tools_enabled", False)
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
        project_id=session.get("project_id"),
        supports_reasoning=supports_reasoning,
        reasoning_enabled_for_call=reasoning_enabled,
        tools_enabled=tools_enabled_flag,
    )
```

- [ ] **Step 2: Smoke-import the orchestrator to catch any signature mismatch**

Run: `PYTHONPATH=. uv run python -c "from backend.modules.chat._orchestrator import run_inference; print('ok')"`
Expected: prints `ok` with no ImportError or SyntaxError.

- [ ] **Step 3: Confirm prompt assembler tests still pass**

Run: `PYTHONPATH=. uv run pytest tests/test_prompt_assembler.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Forward session project_id into prompt assembler"
```

---

### Task 7: Mirror the new field on the frontend types

**Files:**
- Modify: `frontend/src/features/projects/types.ts`

- [ ] **Step 1: Add `system_prompt` to all three TypeScript interfaces**

In `frontend/src/features/projects/types.ts`, modify the three interfaces. `ProjectDto`:

```ts
export interface ProjectDto {
  id: string
  user_id: string
  title: string
  emoji: string | null
  description: string | null
  nsfw: boolean
  pinned: boolean
  sort_order: number
  knowledge_library_ids: string[]
  /**
   * Optional per-project Custom Instructions injected into the
   * assembled system prompt between model-instructions and persona.
   * `null` for projects without CI.
   */
  system_prompt: string | null
  created_at: string
  updated_at: string
}
```

`ProjectCreateDto`:

```ts
export interface ProjectCreateDto {
  title: string
  emoji?: string | null
  description?: string | null
  nsfw?: boolean
  knowledge_library_ids?: string[]
  system_prompt?: string | null
}
```

`ProjectUpdateDto`:

```ts
export interface ProjectUpdateDto {
  title?: string
  emoji?: string | null
  description?: string | null
  nsfw?: boolean
  knowledge_library_ids?: string[]
  /**
   * Omit to leave unchanged. ``null`` clears the CI server-side;
   * a string sets it.
   */
  system_prompt?: string | null
}
```

- [ ] **Step 2: TypeScript build check**

Run from `frontend/`: `pnpm tsc --noEmit`
Expected: PASS — no new type errors. Existing call sites of `ProjectDto` were positional-by-name (object spread) and tolerate the new optional field.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/projects/types.ts
git commit -m "Mirror system_prompt on the frontend project types"
```

---

### Task 8: Add the Custom Instructions textarea to ProjectOverviewTab

**Files:**
- Modify: `frontend/src/features/projects/tabs/ProjectOverviewTab.tsx`
- Test: `frontend/src/features/projects/__tests__/ProjectOverviewTab.test.tsx`

- [ ] **Step 1: Read the existing description-section markup**

Run: `sed -n '230,275p' frontend/src/features/projects/tabs/ProjectOverviewTab.tsx`
Expected: prints the description section markup (label, textarea, classes). The new section uses the same Tailwind classes for visual rhythm.

- [ ] **Step 2: Write failing tests for the new textarea**

Append to `frontend/src/features/projects/__tests__/ProjectOverviewTab.test.tsx` (inside the existing `describe(...)` block; if there's no top-level `describe`, append at the end of the file matching the current style):

```tsx
describe('Custom Instructions field', () => {
  beforeEach(() => {
    patchMock.mockClear()
  })

  const baseProject: ProjectDto = {
    id: 'p1',
    user_id: 'u1',
    title: 'Test',
    emoji: null,
    description: null,
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    system_prompt: null,
    created_at: '2026-05-06T00:00:00Z',
    updated_at: '2026-05-06T00:00:00Z',
  }

  it('renders the textarea with the project current CI', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(
      <ProjectOverviewTab
        project={{ ...baseProject, system_prompt: 'be brief' }}
        onClose={() => {}}
      />,
    )
    const textarea = screen.getByTestId('project-overview-system-prompt') as HTMLTextAreaElement
    expect(textarea.value).toBe('be brief')
  })

  it('PATCHes system_prompt on blur with changed text', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(<ProjectOverviewTab project={baseProject} onClose={() => {}} />)
    const textarea = screen.getByTestId('project-overview-system-prompt')
    fireEvent.focus(textarea)
    fireEvent.change(textarea, { target: { value: 'new ci' } })
    fireEvent.blur(textarea)
    await new Promise((r) => setTimeout(r, 0))
    expect(patchMock).toHaveBeenCalledWith('p1', { system_prompt: 'new ci' })
  })

  it('PATCHes system_prompt: null on blur when emptied', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(
      <ProjectOverviewTab
        project={{ ...baseProject, system_prompt: 'old' }}
        onClose={() => {}}
      />,
    )
    const textarea = screen.getByTestId('project-overview-system-prompt')
    fireEvent.focus(textarea)
    fireEvent.change(textarea, { target: { value: '   ' } })
    fireEvent.blur(textarea)
    await new Promise((r) => setTimeout(r, 0))
    expect(patchMock).toHaveBeenCalledWith('p1', { system_prompt: null })
  })

  it('does not PATCH on blur when text is unchanged', async () => {
    const { ProjectOverviewTab } = await import('../tabs/ProjectOverviewTab')
    render(
      <ProjectOverviewTab
        project={{ ...baseProject, system_prompt: 'same' }}
        onClose={() => {}}
      />,
    )
    const textarea = screen.getByTestId('project-overview-system-prompt')
    fireEvent.focus(textarea)
    fireEvent.blur(textarea)
    await new Promise((r) => setTimeout(r, 0))
    expect(patchMock).not.toHaveBeenCalled()
  })
})
```

(If `ProjectOverviewTab` is exported as a default in the file, change the import to a default import. If the props type differs from `{ project, onClose }`, adjust the test render call accordingly — the subagent must read the existing file to confirm the exact prop signature before writing the test.)

- [ ] **Step 3: Run the tests and confirm they fail**

Run from `frontend/`: `pnpm vitest run src/features/projects/__tests__/ProjectOverviewTab.test.tsx -t 'Custom Instructions'`
Expected: FAIL — element with `data-testid="project-overview-system-prompt"` is not in the DOM.

- [ ] **Step 4: Add state, handler, and markup to `ProjectOverviewTab`**

In `frontend/src/features/projects/tabs/ProjectOverviewTab.tsx`:

a) Add new state declarations alongside the existing `description` state (near line 47):

```tsx
  const [systemPrompt, setSystemPrompt] = useState(project?.system_prompt ?? '')
  const [editingSystemPrompt, setEditingSystemPrompt] = useState(false)
```

b) Mirror the description sync-on-prop-change effect (near line 65):

```tsx
  useEffect(() => {
    if (!editingSystemPrompt) setSystemPrompt(project.system_prompt ?? '')
  }, [project.system_prompt, editingSystemPrompt])
```

c) Add a blur handler near `handleDescriptionBlur`:

```tsx
  const handleSystemPromptBlur = async () => {
    const trimmed = systemPrompt.trim()
    const current = project?.system_prompt ?? ''
    if (trimmed === current) {
      setEditingSystemPrompt(false)
      return
    }
    await patch({ system_prompt: trimmed === '' ? null : trimmed })
    setEditingSystemPrompt(false)
  }
```

d) In the JSX, add a new `<div className="flex flex-col">` block immediately after the description block (between `{/* Description */}` and `{/* NSFW */}`). The Tailwind classes are copied verbatim from the description label and textarea so the visual rhythm matches:

```tsx
        {/* Custom Instructions */}
        <div className="flex flex-col">
          <label
            htmlFor="project-overview-system-prompt"
            className="mb-1 text-[11px] font-mono uppercase tracking-wider text-white/45"
          >
            Custom Instructions
          </label>
          <p className="mb-1.5 text-[11px] text-white/50">
            Sent to the model as instructions for this project. Sits between model-level guidance and the persona.
          </p>
          <textarea
            id="project-overview-system-prompt"
            value={systemPrompt}
            rows={6}
            onChange={(e) => setSystemPrompt(e.target.value)}
            onFocus={() => setEditingSystemPrompt(true)}
            onBlur={() => void handleSystemPromptBlur()}
            placeholder="Optional — instructions sent to the model for chats inside this project."
            data-testid="project-overview-system-prompt"
            className="resize-none rounded-md border border-white/10 bg-white/4 px-3 py-2 text-[13px] text-white/85 placeholder-white/35 outline-none transition-colors focus:border-white/20 focus:bg-white/6"
          />
        </div>
```

- [ ] **Step 5: Run the new tests and confirm they pass**

Run from `frontend/`: `pnpm vitest run src/features/projects/__tests__/ProjectOverviewTab.test.tsx -t 'Custom Instructions'`
Expected: PASS — all four new tests green.

- [ ] **Step 6: Run the full ProjectOverviewTab test file to confirm no regression**

Run: `pnpm vitest run src/features/projects/__tests__/ProjectOverviewTab.test.tsx`
Expected: PASS — pre-existing description / emoji / library tests remain green.

- [ ] **Step 7: Run the full frontend build**

Run from `frontend/`: `pnpm run build`
Expected: PASS — full TypeScript build clean (`tsc -b` is stricter than `tsc --noEmit` and catches issues the previous task would not).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/projects/tabs/ProjectOverviewTab.tsx frontend/src/features/projects/__tests__/ProjectOverviewTab.test.tsx
git commit -m "Add Custom Instructions textarea to project overview tab"
```

---

### Task 9: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Backend pure-unit assembler tests**

Run from repo root:

```bash
PYTHONPATH=. uv run pytest tests/test_prompt_assembler.py tests/test_shared_project_contracts.py -v
```

Expected: PASS — full file green for both modules.

- [ ] **Step 2: Backend DB-bound tests via Docker**

Run from repo root:

```bash
docker compose run --rm backend uv run pytest tests/test_project_repository_system_prompt.py tests/test_project_handlers_mindspace.py -v
```

Expected: PASS. If Docker is unavailable in the subagent's environment, surface this in the final report — do not skip the verification.

- [ ] **Step 3: Frontend type-check + build**

Run from `frontend/`:

```bash
pnpm run build
```

Expected: PASS — full Vite + tsc build clean.

- [ ] **Step 4: Frontend tests**

Run from `frontend/`:

```bash
pnpm vitest run src/features/projects/__tests__/ProjectOverviewTab.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Smoke-import the touched backend modules**

Run from repo root:

```bash
PYTHONPATH=. uv run python -c "from backend.modules.project import get_system_prompt; from backend.modules.chat._prompt_assembler import assemble; from backend.modules.chat._orchestrator import run_inference; print('all imports ok')"
```

Expected: prints `all imports ok`.

- [ ] **Step 6: Subagent reports DO NOT merge / push / branch-switch**

The subagent must include in its final summary:

- All commit SHAs created on the feature branch.
- Test results from steps 1–5.
- An explicit confirmation: "did NOT merge to master, did NOT push, did NOT switch branches".

The main session is responsible for review and merge.
