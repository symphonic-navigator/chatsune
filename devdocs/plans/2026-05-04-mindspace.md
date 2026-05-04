# Mindspace (Projects) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Repo-specific constraints (read before starting any task):**
> - **Subagent dispatch rule:** subagents must NEVER merge, push, or switch branches. The dispatcher (Chris/Claude main session) handles `master`-merges at the end.
> - **Backend tests on host:** the four MongoDB-touching test files require Docker. Either run pytest inside `docker compose exec backend …` for DB tests, or invoke from host with the standard exclude list.
> - **Pytest rootdir on host:** `backend/pyproject.toml` is the configfile, so prepend `PYTHONPATH=$PWD` when running pytest from repo root.
> - **Frontend build check:** always `pnpm run build` (not just `pnpm tsc --noEmit`) — `tsc -b` catches stricter errors that the no-emit path misses.
> - **British English** in code, comments, identifiers.
> - **Module boundaries:** never import from another module's `_*.py` files. Add a public-API method on the owning module instead.
> - **DTOs/topics in `shared/`** only. No magic strings.

**Goal:** Implement the Mindspace (Projects) feature per `devdocs/specs/2026-05-04-mindspace-design.md`, end-to-end across backend + frontend.

**Architecture:** Additive backend changes to `project`, `chat`, `persona`, `storage`, `artefact`, `images`, `knowledge` modules; library-merge extension in chat orchestrator; new frontend surfaces (sidebar projects-zone, in-chat switcher, project-detail-overlay, projects-tab, persona overview selector); reuse of existing `HistoryTab`/`UploadsTab`/`ArtefactsTab`/`ImagesTab` via `projectFilter` prop. All schema changes additive — no migration script required.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, MongoDB 7 (replica-set), Redis, React 18 / TSX / Tailwind, Vite, pnpm, Zustand, custom WebSocket event-bus.

**Spec reference:** `devdocs/specs/2026-05-04-mindspace-design.md` is the authoritative source. Numbers like "spec §6.5" point there.

---

## File Structure

### Backend — files to create
- *(none — all changes extend existing files)*

### Backend — files to modify
- `backend/modules/project/_models.py` — add `knowledge_library_ids`, `description`
- `backend/modules/project/_repository.py` — pinned/cascade/usage methods, sort by `pinned + updated_at`
- `backend/modules/project/_handlers.py` — DELETE with `purge_data`, pinned PATCH, usage include
- `backend/modules/project/__init__.py` — extend public API (`get_library_ids`, `list_project_ids_for_user`, `cascade_delete_project(purge_data=…)`, `remove_library_from_all_projects`, `get_usage_counts`)
- `backend/modules/chat/_models.py` — add `project_id`
- `backend/modules/chat/_repository.py` — `exclude_in_projects` flag, project-list helpers, project-id assignment
- `backend/modules/chat/_handlers.py` — `PATCH /api/chat/sessions/{id}/project`
- `backend/modules/chat/_orchestrator.py` — read `project_lib_ids`, merge into knowledge search
- `backend/modules/chat/__init__.py` — `list_session_ids_for_project`
- `backend/modules/persona/_models.py` — add `default_project_id`
- `backend/modules/persona/_handlers.py` — accept `default_project_id` in PATCH (with `_Unset` sentinel)
- `backend/modules/user/_models.py` — add `recent_project_emojis`
- `backend/modules/user/_handlers.py` — endpoint to bump LRU, fire topic
- `backend/modules/storage/__init__.py` + `_handlers.py` + `_repository.py` — `project_id` query param
- `backend/modules/artefact/__init__.py` + `_handlers.py` + `_repository.py` — `project_id` query param
- `backend/modules/images/__init__.py` + `_handlers.py` + `_repository.py` — `project_id` query param
- `backend/modules/knowledge/_handlers.py` (or wherever `cascade_delete_library` lives) — call `project.remove_library_from_all_projects`
- `backend/main.py` — index init for new compound indexes
- `shared/dtos/project.py` — add `knowledge_library_ids`, `description` to `ProjectDto`/`ProjectCreateDto`/`ProjectUpdateDto`; add `ProjectUsageDto`
- `shared/dtos/chat.py` — add `project_id` to `ChatSessionDto`
- `shared/dtos/persona.py` — add `default_project_id` to `PersonaDto`/`PersonaUpdateDto`
- `shared/dtos/user.py` — add `recent_project_emojis`
- `shared/topics.py` — add `PROJECT_PINNED_UPDATED`, `CHAT_SESSION_PROJECT_UPDATED`, `USER_RECENT_PROJECT_EMOJIS_UPDATED`

### Backend — tests to create / extend
- `backend/tests/modules/project/test_repository.py` — add cases for cascade safe-delete vs full-purge, library cascade, usage counts
- `backend/tests/modules/project/test_handlers.py` — DELETE `?purge_data=true|false`, pinned PATCH, GET `?include_usage=true`
- `backend/tests/modules/chat/test_repository.py` — `exclude_in_projects`, list-by-project
- `backend/tests/modules/chat/test_handlers.py` — `PATCH /api/chat/sessions/{id}/project`
- `backend/tests/modules/chat/test_orchestrator.py` — library merge with project source
- `backend/tests/modules/persona/test_handlers.py` — PATCH `default_project_id` (set/clear/leave)
- `backend/tests/modules/storage/test_handlers.py` — project_id query
- `backend/tests/modules/artefact/test_handlers.py` — project_id query
- `backend/tests/modules/images/test_handlers.py` — project_id query
- `backend/llm_harness/scenarios/library_merge_with_project.json` — manual scenario

### Frontend — files to create
- `frontend/src/features/projects/projectsApi.ts`
- `frontend/src/features/projects/useProjectsStore.ts`
- `frontend/src/features/projects/recentProjectEmojisStore.ts`
- `frontend/src/features/projects/types.ts`
- `frontend/src/features/projects/ProjectSwitcher.tsx`
- `frontend/src/features/projects/ProjectPicker.tsx`
- `frontend/src/features/projects/ProjectPickerMobile.tsx`
- `frontend/src/features/projects/ProjectCreateModal.tsx`
- `frontend/src/features/projects/ProjectDetailOverlay.tsx`
- `frontend/src/features/projects/tabs/ProjectOverviewTab.tsx`
- `frontend/src/features/projects/tabs/ProjectPersonasTab.tsx`
- `frontend/src/features/projects/DeleteProjectModal.tsx`
- `frontend/src/features/projects/projectPill.tsx` — small `[emoji] name` pill component
- `frontend/src/features/projects/__tests__/useProjectsStore.test.ts`
- `frontend/src/features/projects/__tests__/ProjectSwitcher.test.tsx`
- `frontend/src/features/projects/__tests__/ProjectPicker.test.tsx`
- `frontend/src/features/projects/__tests__/ProjectCreateModal.test.tsx`

### Frontend — files to modify
- `frontend/src/app/components/sidebar/Sidebar.tsx` — activate `ZoneSection zone="projects"`, mobile `'projects'` discriminator
- `frontend/src/app/components/sidebar/MobileMainView.tsx` — add Projects entry
- `frontend/src/app/components/user-modal/ProjectsTab.tsx` — replace stub
- `frontend/src/app/components/user-modal/UserModal.tsx` — wire ProjectsTab routing if missing
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — add `projectFilter` prop, "Include project chats" toggle, project pill
- `frontend/src/app/components/user-modal/UploadsTab.tsx` — add `projectFilter` prop
- `frontend/src/app/components/user-modal/ArtefactsTab.tsx` — add `projectFilter` prop
- `frontend/src/app/components/user-modal/PersonasTab.tsx` (or persona overview component) — add Default-Project selector
- *(possibly)* `frontend/src/app/components/.../ImagesTab.tsx` — add `projectFilter` prop *(verify path during Task 26)*
- `frontend/src/app/layouts/AppLayout.tsx` — `filteredProjects` selector, NSFW filter
- `frontend/src/core/websocket/eventBus.ts` — register new topics if a registry exists
- `frontend/src/app/pages/ChatPage.tsx` (or chat top-bar component) — mount `ProjectSwitcher`

---

## Phase 1 — Backend foundation (schema, topics, indexes)

Goal: extend the existing models, DTOs, topic constants, and index definitions. After Phase 1 the backend deserialises new and old documents identically; nothing user-visible changes yet.

### Task 1 — Extend ProjectDocument schema

**Files:**
- Modify: `backend/modules/project/_models.py`
- Modify: `shared/dtos/project.py`

- [ ] **Step 1: Read the current model**

```bash
sed -n '1,80p' backend/modules/project/_models.py
sed -n '1,80p' shared/dtos/project.py
```

- [ ] **Step 2: Add fields to `ProjectDocument` (Pydantic) and DTOs**

In `backend/modules/project/_models.py`, add to `ProjectDocument`:

```python
knowledge_library_ids: list[str] = Field(default_factory=list)
description: str | None = None
```

In `shared/dtos/project.py`:

```python
# In ProjectDto
knowledge_library_ids: list[str] = Field(default_factory=list)
description: str | None = None

# In ProjectCreateDto
knowledge_library_ids: list[str] = Field(default_factory=list)
description: str | None = None

# In ProjectUpdateDto (use _Unset sentinel for nullable)
knowledge_library_ids: list[str] | _Unset = _UNSET
description: str | None | _Unset = _UNSET
```

Add a `ProjectUsageDto`:

```python
class ProjectUsageDto(BaseModel):
    chat_count: int = 0
    upload_count: int = 0
    artefact_count: int = 0
    image_count: int = 0
```

- [ ] **Step 3: Round-trip test**

In `backend/tests/modules/project/test_repository.py`, add:

```python
async def test_project_doc_roundtrips_new_fields(project_repo):
    pid = await project_repo.create(user_id="u1", name="P", emoji=None,
                                     description="hi", knowledge_library_ids=["L1"])
    p = await project_repo.get(pid, "u1")
    assert p.description == "hi"
    assert p.knowledge_library_ids == ["L1"]

async def test_legacy_doc_reads_with_defaults(project_repo, projects_collection):
    # Insert raw old-shape doc with no new fields, no display_order required
    await projects_collection.insert_one({
        "_id": "legacy1", "user_id": "u1", "name": "old",
        "emoji": None, "nsfw": False, "pinned": False,
        "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
    })
    p = await project_repo.get("legacy1", "u1")
    assert p.description is None
    assert p.knowledge_library_ids == []
```

- [ ] **Step 4: Run tests**

```bash
docker compose exec backend pytest backend/tests/modules/project/test_repository.py -v
```

Expected: PASS for both.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/project/_models.py shared/dtos/project.py backend/tests/modules/project/test_repository.py
git commit -m "Extend ProjectDocument with knowledge_library_ids and description"
```

### Task 2 — Add `project_id` to ChatSessionDocument

**Files:**
- Modify: `backend/modules/chat/_models.py`
- Modify: `shared/dtos/chat.py`

- [ ] **Step 1: Add field**

In `_models.py` `ChatSessionDocument`:

```python
project_id: str | None = None
```

In `shared/dtos/chat.py` `ChatSessionDto`:

```python
project_id: str | None = None
```

- [ ] **Step 2: Add test for legacy-doc deserialisation**

```python
async def test_legacy_session_reads_project_id_as_none(chat_repo, sessions_coll):
    await sessions_coll.insert_one({
        "_id": "s1", "user_id": "u1", "title": "old",
        "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
    })
    s = await chat_repo.get_session("s1", "u1")
    assert s.project_id is None
```

- [ ] **Step 3: Run + commit**

```bash
docker compose exec backend pytest backend/tests/modules/chat/test_repository.py -v
git add backend/modules/chat/_models.py shared/dtos/chat.py backend/tests/modules/chat/test_repository.py
git commit -m "Add project_id field to ChatSessionDocument"
```

### Task 3 — Add `default_project_id` to PersonaDocument

**Files:**
- Modify: `backend/modules/persona/_models.py`
- Modify: `shared/dtos/persona.py`

- [ ] **Step 1: Add field**

In `_models.py` `PersonaDocument`:

```python
default_project_id: str | None = None
```

In `shared/dtos/persona.py` — add to `PersonaDto`:

```python
default_project_id: str | None = None
```

And to `PersonaUpdateDto` with `_Unset`:

```python
default_project_id: str | None | _Unset = _UNSET
```

- [ ] **Step 2: Test legacy persona deserialises with `None`**

```python
async def test_legacy_persona_default_project_id_none(persona_repo, personas_coll):
    await personas_coll.insert_one({"_id": "p1", "user_id": "u1", "name": "X",
                                    "created_at": datetime.utcnow(),
                                    "updated_at": datetime.utcnow()})
    p = await persona_repo.get("p1", "u1")
    assert p.default_project_id is None
```

- [ ] **Step 3: Run + commit**

```bash
docker compose exec backend pytest backend/tests/modules/persona/test_repository.py -v
git add backend/modules/persona/_models.py shared/dtos/persona.py backend/tests/modules/persona/test_repository.py
git commit -m "Add default_project_id field to PersonaDocument"
```

### Task 4 — Add `recent_project_emojis` to UserDocument

**Files:**
- Modify: `backend/modules/user/_models.py`
- Modify: `shared/dtos/user.py`

- [ ] **Step 1: Add field**

```python
recent_project_emojis: list[str] = Field(default_factory=list)
```

(in both Document + DTO)

- [ ] **Step 2: Test default-empty on legacy docs**, run, commit.

```bash
git add backend/modules/user/_models.py shared/dtos/user.py backend/tests/modules/user/...
git commit -m "Add recent_project_emojis LRU field to UserDocument"
```

### Task 5 — New topic constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Append to the relevant topic block**

```python
class Topics:
    # ... existing ...
    PROJECT_PINNED_UPDATED              = "project.pinned.updated"
    CHAT_SESSION_PROJECT_UPDATED        = "chat.session.project.updated"
    USER_RECENT_PROJECT_EMOJIS_UPDATED  = "user.recent_project_emojis.updated"
```

- [ ] **Step 2: Verify uniqueness of values**

```bash
docker compose exec backend python -c "from shared.topics import Topics; \
  vs=[v for k,v in Topics.__dict__.items() if isinstance(v,str)]; \
  assert len(vs)==len(set(vs)), 'dup'"
```

- [ ] **Step 3: Commit**

```bash
git add shared/topics.py
git commit -m "Add Mindspace topics: project pinned, session project, user recent emojis"
```

### Task 6 — Idempotent indexes

**Files:**
- Modify: `backend/main.py` (or wherever `init_indexes` per module is wired) — and the per-module `_repository.py` `init_indexes` async function.

- [ ] **Step 1: Add to `chat._repository.init_indexes`**

```python
await sessions.create_index([("user_id", 1), ("project_id", 1), ("updated_at", -1)],
                            name="user_project_updated", background=True)
```

- [ ] **Step 2: Add to `project._repository.init_indexes`**

```python
await projects.create_index([("user_id", 1), ("pinned", -1), ("updated_at", -1)],
                            name="user_pinned_updated", background=True)
```

- [ ] **Step 3: Add to `persona._repository.init_indexes`** (sparse)

```python
await personas.create_index([("user_id", 1), ("default_project_id", 1)],
                            name="user_default_project", sparse=True, background=True)
```

- [ ] **Step 4: Restart backend, verify no errors, commit**

```bash
docker compose restart backend
docker compose logs backend --tail 50 | grep -i index
git add backend/modules/chat/_repository.py backend/modules/project/_repository.py backend/modules/persona/_repository.py
git commit -m "Add Mindspace compound indexes (user/project/updated, user/pinned, user/default_project)"
```

---

## Phase 2 — Project module: public API + endpoints

Goal: backend exposes full Project-CRUD with safe-delete and full-purge variants, library-merge data path, and usage-count endpoint that the delete modal needs.

### Task 7 — Project repository methods

**Files:**
- Modify: `backend/modules/project/_repository.py`

- [ ] **Step 1: Sort listing by `pinned + updated_at`**

```python
async def list_for_user(self, user_id: str) -> list[ProjectDocument]:
    cursor = self._coll.find({"user_id": user_id}).sort(
        [("pinned", -1), ("updated_at", -1)]
    )
    return [ProjectDocument(**doc) async for doc in cursor]
```

- [ ] **Step 2: `get_library_ids(project_id, user_id)`**

```python
async def get_library_ids(self, project_id: str, user_id: str) -> list[str]:
    doc = await self._coll.find_one({"_id": project_id, "user_id": user_id},
                                    projection={"knowledge_library_ids": 1})
    return doc.get("knowledge_library_ids", []) if doc else []
```

- [ ] **Step 3: `remove_library_from_all_projects(library_id)`**

```python
async def remove_library_from_all_projects(self, library_id: str) -> None:
    await self._coll.update_many(
        {"knowledge_library_ids": library_id},
        {"$pull": {"knowledge_library_ids": library_id},
         "$set":  {"updated_at": utcnow()}}
    )
```

- [ ] **Step 4: `set_pinned(project_id, user_id, pinned: bool)`**

```python
async def set_pinned(self, project_id: str, user_id: str, pinned: bool) -> bool:
    res = await self._coll.update_one(
        {"_id": project_id, "user_id": user_id},
        {"$set": {"pinned": pinned, "updated_at": utcnow()}}
    )
    return res.modified_count > 0
```

- [ ] **Step 5: Tests for all four**

In `test_repository.py`, add cases for sort order, library_ids retrieval on missing-project (returns `[]`), library removal across multiple projects, pinned toggle.

- [ ] **Step 6: Run + commit**

### Task 8 — Project public API additions

**Files:**
- Modify: `backend/modules/project/__init__.py`

- [ ] **Step 1: Expose new functions**

```python
from ._repository import ProjectRepository  # already imported
# expose:
async def get_library_ids(project_id: str, user_id: str) -> list[str]:
    return await _repo().get_library_ids(project_id, user_id)

async def list_project_ids_for_user(user_id: str) -> list[str]:
    return [p.id for p in await _repo().list_for_user(user_id)]

async def remove_library_from_all_projects(library_id: str) -> None:
    await _repo().remove_library_from_all_projects(library_id)

async def set_pinned(project_id: str, user_id: str, pinned: bool) -> bool:
    return await _repo().set_pinned(project_id, user_id, pinned)

async def get_usage_counts(project_id: str, user_id: str) -> ProjectUsageDto:
    # delegated to _service.py — see Task 11
    ...

async def cascade_delete_project(project_id: str, user_id: str, *, purge_data: bool) -> None:
    # implemented in _service.py — see Task 9
    ...
```

- [ ] **Step 2: Update __all__ list, commit.**

### Task 9 — `cascade_delete_project` with safe-delete + full-purge

**Files:**
- Create: `backend/modules/project/_service.py` — orchestration logic that talks to other modules' public APIs
- Modify: `backend/modules/project/__init__.py` — export

- [ ] **Step 1: `_service.cascade_delete_project(project_id, user_id, purge_data: bool)`**

```python
from backend.modules import chat as chat_service
from backend.modules import persona as persona_service
from backend.modules import storage as storage_service
from backend.modules import artefact as artefact_service
from backend.modules import images as images_service

async def cascade_delete_project(project_id: str, user_id: str, *,
                                 purge_data: bool, repo: ProjectRepository,
                                 event_bus) -> None:
    project = await repo.get(project_id, user_id)
    if project is None:
        return

    session_ids = await chat_service.list_session_ids_for_project(project_id, user_id)

    if purge_data:
        # Delete sessions (their messages, attachments, artefacts, images
        # cascade through each module's existing session-delete path).
        for sid in session_ids:
            await chat_service.delete_session(sid, user_id)
    else:
        # Detach: set project_id = None on each session, fire one event per session.
        for sid in session_ids:
            await chat_service.set_session_project(sid, user_id, None)

    # Personas with default_project_id pointing at this project → set to None
    await persona_service.clear_default_project_for_all(user_id, project_id)

    # Finally remove the project
    await repo.delete(project_id, user_id)
    await event_bus.publish(Topics.PROJECT_DELETED, {"id": project_id, "user_id": user_id})
```

- [ ] **Step 2: Add tests for both modes**

```python
async def test_safe_delete_detaches_sessions(...):
    # create project + 3 sessions assigned, run safe-delete,
    # verify sessions remain with project_id=None, project gone
async def test_full_purge_deletes_sessions(...):
    # same setup, purge_data=True, verify sessions deleted
async def test_cascade_clears_persona_default(...):
    # persona has default_project_id == this project, after delete it's None
```

- [ ] **Step 3: Run + commit**

### Task 10 — Project handlers / endpoints

**Files:**
- Modify: `backend/modules/project/_handlers.py`

- [ ] **Step 1: Update PATCH to accept `knowledge_library_ids` and `description`**

`apply_update` should call repo `update_partial` with `_Unset`-aware logic; emit `PROJECT_UPDATED`.

- [ ] **Step 2: DELETE with `purge_data` query param**

```python
@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    purge_data: bool = False,
    user: AuthedUser = Depends(get_current_user),
):
    await project_service.cascade_delete_project(
        project_id, user.id, purge_data=purge_data
    )
    return {"ok": True}
```

- [ ] **Step 3: PATCH `/{project_id}/pinned`**

```python
@router.patch("/{project_id}/pinned")
async def set_pinned(
    project_id: str, body: PinnedDto,
    user: AuthedUser = Depends(get_current_user),
):
    ok = await project_service.set_pinned(project_id, user.id, body.pinned)
    if not ok:
        raise HTTPException(404)
    await event_bus.publish(Topics.PROJECT_PINNED_UPDATED,
                            {"id": project_id, "pinned": body.pinned, "user_id": user.id})
    return {"ok": True}
```

- [ ] **Step 4: GET `/{project_id}?include_usage=true`**

```python
@router.get("/{project_id}")
async def get_project(
    project_id: str,
    include_usage: bool = False,
    user: AuthedUser = Depends(get_current_user),
):
    p = await project_service.get_project(project_id, user.id)
    if p is None:
        raise HTTPException(404)
    if not include_usage:
        return p.model_dump()
    usage = await project_service.get_usage_counts(project_id, user.id)
    return {**p.model_dump(), "usage": usage.model_dump()}
```

- [ ] **Step 5: Handler tests**

Cover: DELETE both modes (verify status, events emitted), pinned PATCH (verify event), include_usage shape.

- [ ] **Step 6: Run + commit**

### Task 11 — `get_usage_counts`

**Files:**
- Modify: `backend/modules/project/_service.py`

- [ ] **Step 1: Aggregate per-module counts**

```python
async def get_usage_counts(project_id: str, user_id: str) -> ProjectUsageDto:
    session_ids = await chat_service.list_session_ids_for_project(project_id, user_id)
    if not session_ids:
        return ProjectUsageDto()
    return ProjectUsageDto(
        chat_count    = len(session_ids),
        upload_count  = await storage_service.count_files_for_sessions(session_ids),
        artefact_count= await artefact_service.count_for_sessions(session_ids),
        image_count   = await images_service.count_for_sessions(session_ids),
    )
```

This requires `count_for_sessions` public APIs on each module — see Tasks 16/17/18.

- [ ] **Step 2: Test against fixture data, run, commit**

### Task 12 — Library cascade extension

**Files:**
- Modify: `backend/modules/knowledge/_handlers.py` (find `cascade_delete_library`)

- [ ] **Step 1: Add project cleanup**

```python
from backend.modules import project as project_service

async def cascade_delete_library(library_id: str, user_id: str) -> None:
    # ... existing cleanup of personas + sessions ...
    await project_service.remove_library_from_all_projects(library_id)
```

- [ ] **Step 2: Test the cascade**

```python
async def test_library_cascade_removes_from_projects(...):
    # create project with library, delete library, verify project's
    # knowledge_library_ids no longer contains it
```

- [ ] **Step 3: Run + commit**

---

## Phase 3 — Cross-module additions (chat / persona / storage / artefact / images)

### Task 13 — Chat: list filtering + project-id helpers

**Files:**
- Modify: `backend/modules/chat/_repository.py`
- Modify: `backend/modules/chat/__init__.py`

- [ ] **Step 1: Extend `list_sessions(user_id, exclude_in_projects: bool = True)`**

```python
async def list_sessions(self, user_id: str, exclude_in_projects: bool = True):
    q = {"user_id": user_id}
    if exclude_in_projects:
        q["$or"] = [{"project_id": None}, {"project_id": {"$exists": False}}]
    cursor = self._coll.find(q).sort([("pinned", -1), ("updated_at", -1)])
    return [ChatSessionDocument(**doc) async for doc in cursor]
```

- [ ] **Step 2: `list_sessions_for_project` + `list_session_ids_for_project`**

```python
async def list_sessions_for_project(self, user_id: str, project_id: str):
    cursor = self._coll.find({"user_id": user_id, "project_id": project_id}) \
                       .sort([("pinned", -1), ("updated_at", -1)])
    return [ChatSessionDocument(**doc) async for doc in cursor]

async def list_session_ids_for_project(self, project_id: str, user_id: str) -> list[str]:
    cursor = self._coll.find({"user_id": user_id, "project_id": project_id},
                             projection={"_id": 1})
    return [doc["_id"] async for doc in cursor]
```

- [ ] **Step 3: `set_session_project(session_id, user_id, project_id | None)`**

```python
async def set_session_project(self, session_id: str, user_id: str,
                              project_id: str | None) -> bool:
    res = await self._coll.update_one(
        {"_id": session_id, "user_id": user_id},
        {"$set": {"project_id": project_id, "updated_at": utcnow()}}
    )
    return res.modified_count > 0
```

- [ ] **Step 4: Public-API exports** in `chat/__init__.py`.

- [ ] **Step 5: Tests** (legacy session counts as "outside any project", etc.), run, commit.

### Task 14 — `PATCH /api/chat/sessions/{id}/project`

**Files:**
- Modify: `backend/modules/chat/_handlers.py`

- [ ] **Step 1: Body DTO + endpoint**

```python
class SessionProjectUpdateDto(BaseModel):
    project_id: str | None

@router.patch("/sessions/{session_id}/project")
async def set_session_project(
    session_id: str, body: SessionProjectUpdateDto,
    user: AuthedUser = Depends(get_current_user),
):
    ok = await chat_service.set_session_project(session_id, user.id, body.project_id)
    if not ok:
        raise HTTPException(404)
    await event_bus.publish(Topics.CHAT_SESSION_PROJECT_UPDATED, {
        "id": session_id, "project_id": body.project_id, "user_id": user.id,
    })
    return {"ok": True}
```

- [ ] **Step 2: Endpoint test** (set, clear, 404).

- [ ] **Step 3: Run + commit**

### Task 15 — Persona PATCH supports `default_project_id`

**Files:**
- Modify: `backend/modules/persona/_handlers.py`

- [ ] **Step 1: Honour `_Unset` for the new field in update_partial path**

(Existing pattern is the same as for other nullable fields — copy it for `default_project_id`.)

- [ ] **Step 2: New public API `clear_default_project_for_all(user_id, project_id)`**

```python
async def clear_default_project_for_all(self, user_id: str, project_id: str) -> int:
    res = await self._coll.update_many(
        {"user_id": user_id, "default_project_id": project_id},
        {"$set": {"default_project_id": None, "updated_at": utcnow()}}
    )
    return res.modified_count
```

(emit `PERSONA_UPDATED` per affected persona — fetch IDs, then update + publish in a loop, or rely on a list-affected-then-update helper)

- [ ] **Step 3: Tests for set/clear/leave + cascade-clear**, run, commit.

### Task 16 — Storage: `project_id` query + count helper

**Files:**
- Modify: `backend/modules/storage/_repository.py`, `_handlers.py`, `__init__.py`

- [ ] **Step 1: Repository — accept session_ids filter**

```python
async def list_files_for_sessions(self, session_ids: list[str]) -> list[StorageFileDocument]:
    if not session_ids: return []
    cursor = self._coll.find({"session_id": {"$in": session_ids}})
    return [StorageFileDocument(**doc) async for doc in cursor]

async def count_for_sessions(self, session_ids: list[str]) -> int:
    if not session_ids: return 0
    return await self._coll.count_documents({"session_id": {"$in": session_ids}})
```

If the storage collection lacks a `session_id` field today, fall back to the brief §5.5 walk via `chat_messages.attachment_refs` — implement inside this module's repo, **not** in chat module.

- [ ] **Step 2: Handler — accept `project_id` query param**

```python
@router.get("/files")
async def list_files(
    project_id: str | None = None,
    user: AuthedUser = Depends(get_current_user),
):
    if project_id:
        session_ids = await chat_service.list_session_ids_for_project(project_id, user.id)
        return await storage_service.list_files_for_sessions(session_ids)
    return await storage_service.list_files_for_user(user.id)
```

- [ ] **Step 3: Public API exports** + tests + commit.

### Task 17 — Artefact: `project_id` query + count

Same shape as Task 16 — artefact already has a `session_id` index per spec §3, so the implementation is direct `$in`. Add tests, commit.

### Task 18 — Images: `project_id` query + count

Same shape as Task 16/17. Verify the actual module path during the task (could be `backend/modules/images/` per `ls`). Add tests, commit.

---

## Phase 4 — Library merge in orchestrator

### Task 19 — Read `project_lib_ids` in `run_inference`

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: After session+persona load, fetch project libs**

```python
project_lib_ids: list[str] = []
if session.project_id:
    project_lib_ids = await project_service.get_library_ids(session.project_id, user_id)
```

- [ ] **Step 2: Pass through `_make_tool_executor`**

Find the existing closure that captures `persona_lib_ids` and `session_lib_ids`. Add `project_lib_ids` alongside.

- [ ] **Step 3: Update `knowledge._retrieval.search` signature**

```python
async def search(query: str, *,
                 persona_library_ids: list[str],
                 session_library_ids: list[str],
                 project_library_ids: list[str] = (),
                 ...):
    effective_ids = list(set(persona_library_ids) |
                         set(session_library_ids) |
                         set(project_library_ids))
    ...
```

(Default empty so any caller that doesn't yet pass it keeps working.)

- [ ] **Step 4: Test** — orchestrator unit test that asserts the merged set passed to retrieval includes all three sources de-duplicated.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/knowledge/_retrieval.py backend/tests/...
git commit -m "Library merge: include project knowledge_library_ids at retrieval"
```

### Task 20 — `llm_harness` scenario

**Files:**
- Create: `backend/llm_harness/scenarios/library_merge_with_project.json`

- [ ] **Step 1: Author scenario**

A multi-turn scenario that simulates a chat in a project and triggers a knowledge-tool call. Used for manual verification §14.2.

- [ ] **Step 2: Run via harness**

```bash
uv run python -m backend.llm_harness --from backend/llm_harness/scenarios/library_merge_with_project.json
```

Verify backend logs show `effective_ids` containing the union.

- [ ] **Step 3: Commit**

---

## Phase 5 — Frontend foundation (api / hooks / stores)

### Task 21 — `projectsApi.ts`

**Files:**
- Create: `frontend/src/features/projects/projectsApi.ts`

- [ ] **Step 1: API surface**

```ts
import { apiFetch } from '@/core/api/client'
import type { ProjectDto, ProjectCreateDto, ProjectUpdateDto, ProjectUsageDto } from './types'

export const projectsApi = {
  list:        () => apiFetch<ProjectDto[]>('/api/projects'),
  get:         (id: string, includeUsage = false) =>
                 apiFetch<ProjectDto & { usage?: ProjectUsageDto }>(
                   `/api/projects/${id}${includeUsage ? '?include_usage=true' : ''}`),
  create:      (body: ProjectCreateDto) =>
                 apiFetch<ProjectDto>('/api/projects', { method: 'POST', body }),
  patch:       (id: string, body: ProjectUpdateDto) =>
                 apiFetch<ProjectDto>(`/api/projects/${id}`, { method: 'PATCH', body }),
  delete:      (id: string, purgeData: boolean) =>
                 apiFetch<{ok: true}>(`/api/projects/${id}?purge_data=${purgeData}`,
                                      { method: 'DELETE' }),
  setPinned:   (id: string, pinned: boolean) =>
                 apiFetch<{ok: true}>(`/api/projects/${id}/pinned`,
                                      { method: 'PATCH', body: { pinned } }),
  setSessionProject: (sessionId: string, projectId: string | null) =>
                 apiFetch<{ok: true}>(`/api/chat/sessions/${sessionId}/project`,
                                      { method: 'PATCH', body: { project_id: projectId } }),
}
```

- [ ] **Step 2: Define `types.ts` mirroring the backend DTOs**

- [ ] **Step 3: Commit**

### Task 22 — `useProjectsStore.ts` (Zustand + EventBus)

**Files:**
- Create: `frontend/src/features/projects/useProjectsStore.ts`

- [ ] **Step 1: Store skeleton**

```ts
import { create } from 'zustand'
import { eventBus } from '@/core/websocket/eventBus'
import { projectsApi } from './projectsApi'
import type { ProjectDto } from './types'

type ProjectsState = {
  projects: Record<string, ProjectDto>
  loaded: boolean
  load: () => Promise<void>
  upsert: (p: ProjectDto) => void
  remove: (id: string) => void
}

export const useProjectsStore = create<ProjectsState>((set, get) => ({
  projects: {},
  loaded: false,
  load: async () => {
    const list = await projectsApi.list()
    set({ projects: Object.fromEntries(list.map(p => [p.id, p])), loaded: true })
  },
  upsert: (p) => set(s => ({ projects: { ...s.projects, [p.id]: p } })),
  remove: (id) => set(s => {
    const { [id]: _, ...rest } = s.projects
    return { projects: rest }
  }),
}))

// Event subscriptions:
eventBus.on('project.created',  (e) => useProjectsStore.getState().upsert(e.payload))
eventBus.on('project.updated',  (e) => useProjectsStore.getState().upsert(e.payload))
eventBus.on('project.deleted',  (e) => useProjectsStore.getState().remove(e.payload.id))
eventBus.on('project.pinned.updated', (e) => {
  const p = useProjectsStore.getState().projects[e.payload.id]
  if (p) useProjectsStore.getState().upsert({ ...p, pinned: e.payload.pinned })
})
```

- [ ] **Step 2: Selectors**

```ts
export const useSortedProjects = () => useProjectsStore(s => {
  const list = Object.values(s.projects)
  list.sort((a, b) => Number(b.pinned) - Number(a.pinned)
                   || +new Date(b.updated_at) - +new Date(a.updated_at))
  return list
})
export const usePinnedProjects = () =>
  useSortedProjects().filter(p => p.pinned)
```

- [ ] **Step 3: Test the store**

```ts
// useProjectsStore.test.ts — mock projectsApi.list, assert load() populates,
// dispatch a fake 'project.deleted' event, assert removal.
```

- [ ] **Step 4: Run vitest, commit**

### Task 23 — `recentProjectEmojisStore.ts`

**Files:**
- Create: `frontend/src/features/projects/recentProjectEmojisStore.ts`

- [ ] **Step 1: Mirror existing `recentEmojisStore.ts`** with a separate `safeLocalStorage` key (`chatsune.recentProjectEmojis`).

- [ ] **Step 2: Wire WS event** to merge backend-pushed LRU updates.

- [ ] **Step 3: Test, commit**

### Task 24 — Bootstrap stores in app shell

**Files:**
- Modify: wherever existing stores get loaded on app boot (search `useChatSessions().load` to find the place)

- [ ] **Step 1: Call `useProjectsStore.getState().load()` on auth ready**

- [ ] **Step 2: Frontend build check**

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 3: Commit**

---

## Phase 6 — Sidebar Projects-zone activation

### Task 25 — Render pinned projects in `ZoneSection zone="projects"`

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx` (around line 705)

- [ ] **Step 1: Replace placeholder render with actual list**

```tsx
<ZoneSection
  zone="projects"
  title="Projects"
  onOpenPage={() => openUserModal('projects')}
  empty={{ label: 'No pinned projects · Create one →',
           onClick: () => openProjectCreateModal() }}
>
  {() => pinnedProjects.map(p => (
    <ProjectSidebarItem
      key={p.id} project={p}
      onClick={() => openProjectDetailOverlay(p.id)}
    />
  ))}
</ZoneSection>
```

- [ ] **Step 2: Create `ProjectSidebarItem.tsx`** — emoji + name, hover state, context-menu trigger.

- [ ] **Step 3: Visual smoke test**

Start frontend, log in, pin a project via curl, refresh — verify it appears.

- [ ] **Step 4: Commit**

### Task 26 — Sidebar context menu for pinned project

**Files:**
- Modify: `Sidebar.tsx` / `ProjectSidebarItem.tsx`
- Reuse: existing context-menu pattern from PersonaItem / HistoryItem

- [ ] **Step 1: Items: Pin/Unpin · Edit · Delete · Open**

`Edit` → opens project-detail-overlay overview tab. `Delete` → opens DeleteProjectModal (Task 47). Context-menu pattern is the same as PersonaItem; copy structure.

- [ ] **Step 2: Test (vitest) + commit**

### Task 27 — Mobile Projects entry

**Files:**
- Modify: `frontend/src/app/components/sidebar/MobileMainView.tsx`
- Modify: `Sidebar.tsx:213` — add `'projects'` to the `MobileView` union

- [ ] **Step 1: New row + nav action**, route into mobile flyout that lists projects (reuses `ProjectsTab` rendering).

- [ ] **Step 2: Test on viewport ≤lg**, commit.

---

## Phase 7 — In-chat switcher + Project-Create-Modal

### Task 28 — `ProjectSwitcher` component (chat top-bar)

**Files:**
- Create: `frontend/src/features/projects/ProjectSwitcher.tsx`
- Modify: chat top-bar host (likely `frontend/src/app/pages/ChatPage.tsx` or a header component — locate via `rg "top-bar" frontend/src/`)

- [ ] **Step 1: Component skeleton**

```tsx
type Props = { sessionId: string, currentProjectId: string | null }
export function ProjectSwitcher({ sessionId, currentProjectId }: Props) {
  const project = useProjectsStore(s =>
    currentProjectId ? s.projects[currentProjectId] : null)
  const [pickerOpen, setPickerOpen] = useState(false)

  return (
    <div className="flex items-center gap-1">
      <button onClick={() => openProjectDetailOverlay(currentProjectId)}
              disabled={!currentProjectId}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-white/5">
        <span className="text-base">{project?.emoji ?? '—'}</span>
        <span className="text-sm">{project?.name ?? 'No project'}</span>
      </button>
      <button onClick={() => setPickerOpen(true)}
              className="px-1 py-1 rounded hover:bg-white/5">▾</button>
      {pickerOpen && (
        <ProjectPicker
          sessionId={sessionId}
          currentProjectId={currentProjectId}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Mount in chat top-bar**

- [ ] **Step 3: Vitest snapshot for "no project" / "with project"**

- [ ] **Step 4: Commit**

### Task 29 — `ProjectPicker` (desktop dropdown)

**Files:**
- Create: `frontend/src/features/projects/ProjectPicker.tsx`

- [ ] **Step 1: Picker contents**

Always-present search input on top, then list:
1. "— No project" row
2. Project items (emoji + name)
3. "+ Create new project…" row

Filter list by sanitised mode (skip NSFW projects when sanitised) — see Task 41.

- [ ] **Step 2: On select**

```ts
await projectsApi.setSessionProject(sessionId, selectedProjectId /* or null */)
// Backend emits CHAT_SESSION_PROJECT_UPDATED → store updates → component re-renders
onClose()
```

- [ ] **Step 3: "+ Create new project…" → open `ProjectCreateModal`, on success auto-PATCH session to new id**

- [ ] **Step 4: Tests, commit**

### Task 30 — `ProjectPickerMobile` (fullscreen overlay)

**Files:**
- Create: `frontend/src/features/projects/ProjectPickerMobile.tsx`

- [ ] **Step 1: Mirror "Start new chat" mobile overlay** — search bar at top, list below, close arrow top-left.

- [ ] **Step 2: `useViewport()` switches `<ProjectPicker>` vs `<ProjectPickerMobile>`** in the switcher.

- [ ] **Step 3: Manual test on viewport ≤lg, commit**

### Task 31 — `ProjectCreateModal`

**Files:**
- Create: `frontend/src/features/projects/ProjectCreateModal.tsx`

- [ ] **Step 1: Form fields**

Name (required, autofocus), Emoji (picker w/ `recentProjectEmojisStore`), Description (textarea), NSFW toggle, Knowledge libraries (multi-select — reuse the persona library picker if one exists; otherwise inline a small one).

- [ ] **Step 2: Submit → `projectsApi.create(...)` → store upsert**, return new project to caller.

- [ ] **Step 3: Tests for required validation, NSFW default-off, multi-select, commit**

---

## Phase 8 — `UserModal/ProjectsTab`

### Task 32 — Replace stub `ProjectsTab.tsx`

**Files:**
- Modify: `frontend/src/app/components/user-modal/ProjectsTab.tsx`

- [ ] **Step 1: List/search/filter UI**

```tsx
export function ProjectsTab() {
  const projects = useSortedProjects()
  const sanitised = useSanitisedMode().isSanitised
  const visible = sanitised ? projects.filter(p => !p.nsfw) : projects
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all'|'pinned'>('all')
  const matches = visible.filter(p =>
    p.name.toLowerCase().includes(query.toLowerCase()) &&
    (filter === 'all' || p.pinned))
  // ... render header (search, filter pill, +New button) + list
}
```

- [ ] **Step 2: Click on item → `openProjectDetailOverlay(id)`**

- [ ] **Step 3: "+ New Project" → `ProjectCreateModal` → on success, optionally open detail**

- [ ] **Step 4: Vitest, commit**

---

## Phase 9 — Project-Detail-Overlay shell + tabs

### Task 33 — Overlay shell

**Files:**
- Create: `frontend/src/features/projects/ProjectDetailOverlay.tsx`

- [ ] **Step 1: Mirror `PersonaDetailOverlay` shell** — focus trap, escape close, click-outside, tab strip on top.

- [ ] **Step 2: Tab strip** — Overview, Personas, Chats, Uploads, Artefacts, Images.

- [ ] **Step 3: Render the selected tab's component** (Tasks 34–38).

- [ ] **Step 4: Vitest, commit**

### Task 34 — Overview tab

**Files:**
- Create: `frontend/src/features/projects/tabs/ProjectOverviewTab.tsx`

- [ ] **Step 1: Layout**

Big emoji (clickable → emoji picker), inline-edit name, textarea description (save on blur), NSFW toggle, knowledge libraries multi-select, danger-zone delete button (opens `DeleteProjectModal`).

- [ ] **Step 2: Each field saves via `projectsApi.patch(id, ...)`**

- [ ] **Step 3: Vitest, commit**

### Task 35 — Personas tab (default-personas list + actions)

**Files:**
- Create: `frontend/src/features/projects/tabs/ProjectPersonasTab.tsx`

- [ ] **Step 1: Read personas filtered by `default_project_id == projectId`** (selector on persona store)

- [ ] **Step 2: Per-row actions**

- *Start chat here* — calls existing `createChatSession({ persona_id, project_id: this_project })` API.
- *Remove from project* — `personaApi.patch(persona_id, { default_project_id: null })`.

- [ ] **Step 3: "+ Add persona" picker**

```tsx
function AddPersonaButton({ projectId }: { projectId: string }) {
  // open picker; on select:
  const target = await pickPersona() // existing picker pattern
  if (target.default_project_id && target.default_project_id !== projectId) {
    if (!await confirm(`${target.name} is currently default in '${
      projects[target.default_project_id]?.name
    }'. Switch?`)) return
  }
  await personaApi.patch(target.id, { default_project_id: projectId })
}
```

- [ ] **Step 4: Sort alphabetically by persona name**

- [ ] **Step 5: Vitest, commit**

### Task 36 — `HistoryTab projectFilter` prop

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx`

- [ ] **Step 1: Add prop**

```tsx
type Props = { projectFilter?: string }
```

- [ ] **Step 2: When prop set**: query sessions via `chat/sessions?project_id=...`, hide the "include project chats" toggle.

- [ ] **Step 3: When prop unset (UserModal context)**: default `exclude_in_projects=true`. Add the toggle "Include project chats" with persistent state in `safeLocalStorage`.

- [ ] **Step 4: Project pill component**

```tsx
function ProjectPill({ projectId }: { projectId: string }) {
  const p = useProjectsStore(s => s.projects[projectId])
  if (!p) return null
  return (
    <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]
                     bg-white/5 text-white/70 font-mono">
      {p.emoji} {p.name}
    </span>
  )
}
```

Render next to title when "include project chats" is on AND the session has `project_id`.

- [ ] **Step 5: Vitest for both modes, commit**

### Task 37 — `UploadsTab` / `ArtefactsTab` / `ImagesTab` `projectFilter` prop

**Files:**
- Modify: `frontend/src/app/components/user-modal/UploadsTab.tsx`
- Modify: `frontend/src/app/components/user-modal/ArtefactsTab.tsx`
- Modify: (locate ImagesTab — search via `rg ImagesTab frontend/src/`)

- [ ] **Step 1: Each accepts `projectFilter?: string`**, calls its API endpoint with the query param when set.

- [ ] **Step 2: Mobile single-column** when `projectFilter` is set (project-detail-overlay context).

- [ ] **Step 3: Vitest, commit**

### Task 38 — Wire ProjectDetailOverlay tabs to reused components

In Task 33 you already mounted these tabs; this step verifies the prop flows through:

```tsx
case 'chats':     return <HistoryTab projectFilter={projectId} />
case 'uploads':   return <UploadsTab projectFilter={projectId} />
case 'artefacts': return <ArtefactsTab projectFilter={projectId} />
case 'images':    return <ImagesTab projectFilter={projectId} />
```

- [ ] **Step 1: Sanity test** — open overlay, verify counts match (compare against UserModal HistoryTab with toggle on, filtered).

- [ ] **Step 2: Commit if anything wasn't wired in Task 33**

---

## Phase 10 — Persona overview default-project selector

### Task 39 — Persona Overview field

**Files:**
- Modify: persona overview component (locate via `rg "Overview" frontend/src/.*persona`)

- [ ] **Step 1: Add field**

```tsx
<Field label="Default project">
  <ProjectPicker /* simplified: list only, "— No default", "+ Create new" */
    value={persona.default_project_id}
    onChange={async (newId) => {
      await personaApi.patch(persona.id, { default_project_id: newId })
    }}
  />
</Field>
```

- [ ] **Step 2: Vitest, commit**

### Task 40 — Honour persona default at "new chat" trigger points

**Files:**
- Modify: wherever `createChatSession` is called from neutral triggers (sidebar persona pin click, persona overview "Start chat", PersonasTab "Start chat")

- [ ] **Step 1: Pass `project_id = persona.default_project_id` when starting from neutral context**

- [ ] **Step 2: Verify context-bound triggers (project-overlay personas tab "Start chat here") still pass the surrounding project_id (Task 35 already does this — re-test)**

- [ ] **Step 3: Manual test — Worf with default Star Trek, click from sidebar → lands in Star Trek; click from a different project's personas tab → lands in that project**

- [ ] **Step 4: Commit**

---

## Phase 11 — NSFW filtering across surfaces

### Task 41 — `filteredProjects` in `AppLayout`

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx` (around lines 83–96, where personas/sessions filters live)

- [ ] **Step 1: Add memo**

```tsx
const filteredProjects = useMemo(
  () => isSanitised
    ? Object.values(projects).filter(p => !p.nsfw)
    : Object.values(projects),
  [projects, isSanitised]
)
```

- [ ] **Step 2: Pass into Sidebar / UserModal-tabs / ProjectSwitcher**

(or expose a hook `useFilteredProjects()` and consume in those surfaces)

- [ ] **Step 3: Vitest, commit**

### Task 42 — Apply filter to all surfaces

**Files:**
- Modify: `Sidebar.tsx`, `ProjectsTab.tsx`, `ProjectPicker.tsx`, `ProjectPickerMobile.tsx`, `ProjectPersonasTab.tsx` (the "+ Add persona" picker), `HistoryTab.tsx` (with toggle on)

- [ ] **Step 1: Each surface consumes `useFilteredProjects()` instead of all projects**

- [ ] **Step 2: Visual test in sanitised mode**, commit.

### Task 43 — Active NSFW chat keeps showing project

**Files:**
- Modify: `ProjectSwitcher.tsx`

- [ ] **Step 1: When current session has a project_id, render the project from the unfiltered store, not from `filteredProjects`** — so that an NSFW project remains visible to the user who is already in it.

- [ ] **Step 2: Vitest covering this case, commit**

---

## Phase 12 — Delete modal

### Task 44 — `DeleteProjectModal`

**Files:**
- Create: `frontend/src/features/projects/DeleteProjectModal.tsx`

- [ ] **Step 1: Component**

```tsx
export function DeleteProjectModal({ projectId, onClose }: Props) {
  const [usage, setUsage] = useState<ProjectUsage | null>(null)
  const [purge, setPurge] = useState(false)
  useEffect(() => {
    projectsApi.get(projectId, true).then(r => setUsage(r.usage ?? null))
  }, [projectId])

  const submit = async () => {
    await projectsApi.delete(projectId, purge)
    onClose()
  }

  return (
    <Modal onClose={onClose}>
      <h2>Delete project "{name}"</h2>
      <p>After deletion, this project will be removed.<br/>
         Its {usage?.chat_count ?? 0} chats will return to your global history.</p>
      <label>
        <input type="checkbox" checked={purge}
               onChange={e => setPurge(e.target.checked)}/>
        Also delete all data permanently<br/>
        <small>{usage && (
          `${usage.chat_count} chats · ${usage.upload_count} uploads ·
           ${usage.artefact_count} artefacts · ${usage.image_count} images`
        )}<br/>This cannot be undone.</small>
      </label>
      <Button onClick={onClose}>Cancel</Button>
      <Button danger={purge} onClick={submit}>
        {purge ? 'Delete project + all data' : 'Delete project'}
      </Button>
    </Modal>
  )
}
```

- [ ] **Step 2: Vitest** — verify counts render, button label switches, submit calls correct endpoint.

- [ ] **Step 3: Commit**

---

## Phase 13 — Final wiring + frontend build verify

### Task 45 — All entry points wired

- [ ] **Step 1: Sidebar Pinned-Project click → `openProjectDetailOverlay`**
- [ ] **Step 2: ProjectsTab item click → same**
- [ ] **Step 3: Switcher emoji+name click → same**
- [ ] **Step 4: Sidebar empty state "Create one →" → `ProjectCreateModal`**
- [ ] **Step 5: ProjectsTab "+ New Project" → same**
- [ ] **Step 6: Switcher "+ Create new project…" → same, then auto-PATCH active session**
- [ ] **Step 7: Persona Overview "+ Create new project…" picker entry → same, then auto-PATCH persona default**

### Task 46 — Frontend build

- [ ] **Step 1: Type-check + build**

```bash
cd frontend && pnpm run build
```

Expected: green, no errors.

- [ ] **Step 2: Vitest full run**

```bash
cd frontend && pnpm test --run
```

- [ ] **Step 3: Commit any small fixes**

### Task 47 — Backend full test pass

- [ ] **Step 1: In Docker**

```bash
docker compose exec backend pytest backend/tests -v
```

- [ ] **Step 2: Commit any small fixes**

---

## Phase 14 — Manual verification

### Task 48 — Run spec §14 step-by-step

The spec lists 18 manual verification steps in §14. Run them in order on a real device (desktop + mobile breakpoint via DevTools or actual phone).

For each pass, mark the checkbox; if any step fails, file a follow-up task and fix before considering the feature shipped.

- [ ] §14.1  — Backwards compatibility: old session opens, library merge does not pollute
- [ ] §14.2  — Library merge: Worf in Star Trek project pulls Klingons + Star Trek libs, dedup'd
- [ ] §14.3  — Cascade safe-delete: project gone, sessions detached, persona defaults cleared
- [ ] §14.4  — Cascade full-purge: sessions, messages, uploads, artefacts, images all gone; personas only lose default
- [ ] §14.5  — Library cascade: deleting library purges from both persona and project
- [ ] §14.6  — Sidebar pin/unpin via context menu
- [ ] §14.7  — In-chat switcher (desktop): "no project", different project, "+ create new"
- [ ] §14.8  — In-chat switcher (mobile): fullscreen overlay
- [ ] §14.9  — Persona default → neutral trigger lands in default project
- [ ] §14.10 — Personas-tab "Start chat here" lands in *this* project (context wins)
- [ ] §14.11 — Adding persona that's already-default elsewhere → confirmation dialog → switches
- [ ] §14.12 — Reused tab components work in both UserModal and Project-overlay
- [ ] §14.13 — HistoryTab "Include project chats" toggle + project pill
- [ ] §14.14 — Sanitised mode hides NSFW projects across all surfaces
- [ ] §14.15 — Sanitised + active NSFW chat: chat stays open, switcher still shows project
- [ ] §14.16 — Delete modal counts accurate
- [ ] §14.17 — Project emoji LRU separate from chat-message LRU
- [ ] §14.18 — Empty-state "No pinned projects · Create one →" works

### Task 49 — Final merge to master

This task is for the **dispatcher**, not the subagent.

- [ ] **Step 1: Review the worktree's branch end-state** — diff vs master, all phases committed.
- [ ] **Step 2: Merge to master**

```bash
git checkout master
git merge <feature-branch> --no-ff -m "Merge Mindspace (Projects) feature"
```

- [ ] **Step 3: Push** (only if Chris explicitly asks; default no-push).

---

## Self-Review checklist (run before dispatching)

- All 11 spec sections (§1–§16) referenced by at least one task
- No "TBD"/"TODO"/"implement later" in the plan body
- Type names consistent: `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto`, `ProjectUsageDto`, `useProjectsStore`, `projectsApi`
- Endpoint paths consistent with spec §5.4: `/api/projects`, `/api/projects/{id}/pinned`, `/api/chat/sessions/{id}/project`
- Topics consistent with spec §5.7: `PROJECT_PINNED_UPDATED`, `CHAT_SESSION_PROJECT_UPDATED`, `USER_RECENT_PROJECT_EMOJIS_UPDATED`
- All Sub-skill prerequisites called out at the top
