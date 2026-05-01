# Projects — Feature Brief

**Status:** Brainstorm-ready draft.
**Owner:** Chris.
**Last updated:** 2026-05-01.

This brief is the single document you need to walk into a new Claude session and say "let's design this". It captures the product vision, the existing scaffolding, the data-model and UX implications, the open questions, and explicit non-goals. It is intentionally analytical, not implementation-ready — the actual plan will be drafted afterwards via `superpowers:brainstorming` → `superpowers:writing-plans`.

---

## 1. Vision

Chats in Chatsune today live in one flat, persona-grouped history list. As power users accumulate sessions, the list becomes the bottleneck: themes are forgotten, related work scatters, and uploaded material is hard to find again. **Projects** are the second axis of organisation — orthogonal to personas — that makes long-running, theme-bound work first-class.

The benchmark is **Claude.ai Projects** (custom instructions + knowledge files + chats), **ChatGPT Projects** (folders + project files), and **Grok Projects** (folders + memory). Chatsune's differentiator is its existing **Library** abstraction: knowledge isn't tied to a project (or persona) directly, it lives in reusable Libraries that any persona or project can subscribe to. That single architectural choice gives us strictly more expressive power than any competitor and turns Projects from "a folder with bonus files" into "a folder with a knowledge graph".

### What we want users to feel

- Projects are **lightweight**: one click to create, drop a chat in, done.
- They are **honest**: no magic. Files in the project view are exactly the files of its chats — no separate "project files" silo to keep in sync.
- They are **expressive**: one project can pull in three knowledge libraries; the same library can be reused across projects and personas.
- They are **personal**: emoji, NSFW gating, and pinning all carry over.
- They are **calm**: the sidebar stays scannable even with 50 personas, 30 projects, and 200 chats — the three-zone capped layout is the load-bearing UX decision.

### What "better than xAI / ChatGPT / Claude" means concretely

| Capability | Claude.ai | ChatGPT | Grok | Chatsune target |
|---|---|---|---|---|
| Folder-style chat grouping | ✓ | ✓ | ✓ | ✓ |
| Reusable knowledge containers | ✗ (per-project files only) | ✗ | ✗ | ✓ (Libraries, shared) |
| Persona + Project library merge | ✗ (no personas) | ✗ (no personas) | ✗ (no personas) | ✓ (unique-merge) |
| Project emoji w/ separate LRU | ✗ | ✗ | ✗ | ✓ |
| NSFW-aware sanitised mode | ✗ | ✗ | ✗ | ✓ |
| Aggregated artefact view per project | ✗ | partial | ✗ | ✓ (LLM artefacts + uploads) |
| Self-hosted, BYOK, multi-provider | ✗ | ✗ | ✗ | ✓ |

The two unique wins are the **library merge** and **NSFW gating**. Everything else is feature parity with polish.

---

## 2. Feature scope (user-facing)

In numbered form so we can refer back to them throughout the brief:

1. **Project = container for chats.** A chat session can belong to at most one project, or to none. Reassignment is allowed at any time.
2. **Aggregated files & artefacts view.** Per project, show all user-uploaded files and all LLM-generated artefacts across all of its chats, in a single browsable view.
3. **Optional emoji per project**, picked via the existing emoji picker, but with a **separate LRU list** from the chat-message emoji picker.
4. **Library assignment per project**, mirroring the persona–library mechanic. When a chat belongs to a project, the libraries available to that chat's knowledge search are `unique(persona_libraries ∪ project_libraries)`.
5. **Hidden from default history.** Chats inside a project no longer appear in the global history list — they are reachable only via their project.
6. **NSFW flag per project.** Projects can be marked NSFW; in sanitised mode they vanish from the sidebar, modals, and any other surface, just like NSFW personas do today.
7. **Sidebar entry above History.** New "Projects" navigation row, between Personas and History.
8. **Desktop sidebar redesign** — the most disruptive change. Three pinned zones, each capped at 33% of the available vertical space; everything else moves into modals.
9. **Mobile parity.** The sidebar drawer needs the same Projects access path; the modal pattern carries over to the mobile slide-out.

---

## 3. Existing scaffolding — what's already in the repo

The repository already contains a deliberately-disabled Projects skeleton. Reading these files first will save hours of re-discovery.

### Backend

- **Module exists:** `backend/modules/project/` with `_repository.py`, `_handlers.py`, `_models.py`, public API in `__init__.py`. Wired up in `backend/main.py:63` (router include + `init_indexes`).
- **DTOs exist:** `shared/dtos/project.py` with `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto`, plus a working `_Unset` sentinel for distinguishing "set to null" from "do not touch" in PATCH bodies.
- **Topics exist:** `Topics.PROJECT_CREATED`, `Topics.PROJECT_UPDATED`, `Topics.PROJECT_DELETED` in `shared/topics.py:116`.
- **Project doc fields today:** `id`, `user_id`, `name`, `emoji`, `nsfw`, `pinned`, `display_order`, `created_at`, `updated_at`. Missing: `library_ids`, plus dedicated endpoints for pinning/reorder/library mutation.
- **Chat session export allow-list already accommodates `project_id`** — see the comment at `backend/modules/chat/__init__.py:44`. The author of that comment intended for the field to be added later without changing the export logic. It is currently absent from `ChatSessionDocument`.

### Frontend

- **Hidden NavRow:** `Sidebar.tsx:926` has `// Projects desktop NavRow hidden`. Same for the collapsed rail (`Sidebar.tsx:525`) and `UserModal.tsx:267`.
- **Type already widened in anticipation:** `flyoutTab: 'history' | null` at `Sidebar.tsx:211` carries the comment "keep the union shape so re-enabling Projects later is a one-line widening".
- **Placeholder route:** `frontend/src/app/pages/ProjectsPage.tsx` exists, currently a stub.
- **Mobile view union missing entry:** `type MobileView = 'main' | 'new-chat' | 'history' | 'bookmarks'` at `Sidebar.tsx:213` — Projects to be added.
- **No `useProjects` hook, no `projectsApi.ts`, no `recentProjectEmojisStore`, no Project-related event subscription** — these are the four greenfield additions on the frontend.

### What this means

There is no design lock-in. The skeleton is small enough that we can evolve the data model freely. The disabling comments are a clean to-do list, not a deferred half-finished implementation.

---

## 4. Data model

### 4.1 `projects` collection (extension of existing)

```python
class ProjectDocument:
    id: str                                   # UUID, existing
    user_id: str                              # existing
    name: str                                 # existing
    emoji: str | None                         # existing
    nsfw: bool = False                        # existing
    pinned: bool = False                      # existing
    display_order: int = 0                    # existing
    knowledge_library_ids: list[str] = []     # NEW — mirrors persona schema
    description: str | None = None            # NEW (open question, see §10)
    created_at: datetime
    updated_at: datetime
```

Pattern reference: persona's `knowledge_library_ids` lives as a raw-dict field, not declared on the Pydantic doc. Works fine because absent ⇒ empty list. Same applies here. The DTO **does** declare it explicitly, because the wire format must be predictable.

### 4.2 `chat_sessions` collection — new field

```python
project_id: str | None = None    # NEW
```

Default `None`. No backfill needed — missing field is read as `None` everywhere via `doc.get("project_id")`.

Cascade rules:
- Delete project → set `project_id = None` on all member sessions (do **not** delete the chats).
- Delete chat session → no effect on project.
- Move chat between projects → simple `$set`.

### 4.3 No new collection for project–library join

Just like persona–library today, this is a `list[str]` array on the project doc. Cascade is handled by extending `knowledge.cascade_delete_library` to call a new `project.remove_library_from_all_projects(library_id)` public function — same pattern as `persona.remove_library_from_all_personas`.

### 4.4 No new collection for files-in-project

The aggregated files view is **derived**, not stored. See §5.5.

### 4.5 Indexes to add

- `chat_sessions`: compound `[user_id, project_id, updated_at desc]` — covers both "list project X's sessions" and "list global history excluding any project". Old single index on `[user_id, updated_at desc]` stays for backwards compatibility during the rolling restart.
- `projects`: `[user_id, pinned desc, display_order asc]` for sidebar listing.

---

## 5. Backend architecture

### 5.1 Module surface (project module)

Public API additions on top of what exists:

```python
# backend/modules/project/__init__.py
async def get_project(project_id, user_id) -> ProjectDto | None
async def list_projects_for_user(user_id) -> list[ProjectDto]
async def get_library_ids(project_id, user_id) -> list[str]   # NEW — used by chat orchestrator
async def remove_library_from_all_projects(library_id) -> None  # NEW — used by knowledge cascade
async def cascade_delete_project(project_id, user_id) -> None  # NEW — clears project_id on sessions
async def list_project_ids_for_user(user_id) -> list[str]      # NEW — used by chat history filter
```

### 5.2 Endpoints

```
GET    /api/projects                              list (sorted: pinned desc, display_order asc, updated_at desc)
POST   /api/projects                              create
GET    /api/projects/{id}                         single
PATCH  /api/projects/{id}                         partial update (name, emoji, nsfw, description)
PUT    /api/projects/{id}                         full replace
DELETE /api/projects/{id}                         soft-delete or hard-delete (open Q §10)
PATCH  /api/projects/{id}/pinned                  dedicated endpoint, fires PROJECT_PINNED_UPDATED
PATCH  /api/projects/reorder                      bulk reorder, like personas
GET    /api/projects/{id}/knowledge               list library_ids
PUT    /api/projects/{id}/knowledge               set library_ids
GET    /api/projects/{id}/sessions                list sessions in project (delegates to chat module)
GET    /api/projects/{id}/files                   aggregated uploads + artefacts (see §5.5)
```

Pattern note: persona-pinning today goes through generic `PATCH /personas/{id}` and emits `PERSONA_UPDATED`, while session-pinning has a dedicated endpoint and `CHAT_SESSION_PINNED_UPDATED` topic. The latter is cleaner — we mirror it for projects.

### 5.3 Chat module additions

- `ChatSessionDocument` gains `project_id: str | None`.
- `list_sessions(user_id, exclude_in_projects: bool = True)` — default behaviour for global history changes to "exclude sessions where `project_id` is set".
- `list_sessions_for_project(user_id, project_id)` — used by the project module's `/api/projects/{id}/sessions`.
- Move-chat-into-project: new endpoint `PATCH /api/chat/sessions/{id}/project` with body `{"project_id": str | null}`. Emits a single `CHAT_SESSION_PROJECT_UPDATED` event.

### 5.4 Library merge — the load-bearing change

The merge point is **a single line** in `backend/modules/knowledge/_retrieval.py:25`:

```python
effective_ids = list(set(persona_library_ids + session_library_ids))
```

The orchestrator (`backend/modules/chat/_orchestrator.py:189–256`) builds a closure with `persona_lib_ids` and `session_lib_ids`. We extend that closure with `project_lib_ids`:

```python
# in run_inference, after loading session and persona:
project_lib_ids: list[str] = []
if session.get("project_id"):
    project_lib_ids = await project_service.get_library_ids(session["project_id"], user_id)
```

Then `_make_tool_executor` accepts a third argument and `_retrieval.search` does:

```python
effective_ids = list(set(persona_library_ids + session_library_ids + project_library_ids))
```

The Knowledge module itself is unaware of the new source. This respects module boundaries: the chat orchestrator owns the composition; knowledge owns the search; project owns its own library list. **No internal-import shortcuts.**

### 5.5 Aggregated files endpoint

`GET /api/projects/{id}/files` returns merged uploads + artefacts. Two-step internal flow:

1. Get session_ids in the project: `chat.list_session_ids_for_project(project_id, user_id)`.
2. For each subsystem, call its own public API:
   - **Uploads**: ask `storage.list_files_for_sessions(session_ids)`. This is a NEW public function. Underlying implementation walks `chat_messages` (which already has a `session_id` index) collecting `attachment_refs.file_id`, then `storage_repo.find_by_ids(file_ids)`. Heavy but acceptable for a viewer used a few times per project.
   - **Artefacts**: call `artefact.list_for_sessions(session_ids)` — the artefact collection already has a `session_id` index, so this is a single `$in` query.
3. Return a unified DTO: `{uploads: [...], artefacts: [...]}` with paging cursors per array.

Trade-off note: building a `session_id` denormalised index on `storage_files` (currently absent) would make query 1 trivial, but introduces a write-time cost on every upload and a migration headache. The two-step flow is cheap enough at expected sizes to defer that optimisation.

### 5.6 Events / topics

New topics in `shared/topics.py`:

```python
PROJECT_PINNED_UPDATED      = "project.pinned.updated"
PROJECT_REORDERED            = "project.reordered"
PROJECT_LIBRARIES_UPDATED    = "project.libraries.updated"
CHAT_SESSION_PROJECT_UPDATED = "chat.session.project.updated"
USER_RECENT_PROJECT_EMOJIS_UPDATED = "user.recent_project_emojis.updated"  # see §6.5
```

---

## 6. Frontend architecture

### 6.1 Desktop sidebar redesign — three capped zones

Today the sidebar is one big scroll container; pinned items just live above the fold. Going forward:

```
┌ Logo + collapse                                ┐
│ AdminBanner (admin only)                       │
│ NewChat row                                    │
│ Personas (label + collapse toggle)             │
│   ├─ pinned personas (max 33% of free space)   │
│   └─ "Personas →" (opens modal)                │
│ Projects (label + collapse toggle)   ← NEW    │
│   ├─ pinned projects (max 33% of free space)  │
│   └─ "Projects →" (opens modal)               │
│ History (label + collapse toggle)              │
│   ├─ pinned chats (max 33% of free space)     │
│   └─ "History →" (opens modal)                │
└ Bottom-nav (Knowledge / Bookmarks / Uploads / Artefacts / Images / Sanitised toggle / User row) ┘
```

The "free space" is the height of the scroll container minus the three section labels and toggles. Each zone gets `max-height: calc((100% - <header rows>) / 3)` plus `overflow-y: auto`. If a zone is collapsed, the others get its share. This is honest UX: the sidebar promises "you can always see your three categories of pinned things at once", which today's sidebar does not promise.

Implementation note: the existing collapsible-section state pattern (`useState` + `safeLocalStorage`) extends cleanly. Each zone's open/closed flag lives in localStorage under a new key.

### 6.2 Search

Search-by-text is **modal-only** going forward. The sidebar gets simpler — the inline history search input goes away. Each modal (Personas, Projects, History) has its own search. Easier to focus, easier to read.

### 6.3 Modals

Reuse the existing `UserModal` skeleton (`absolute inset-0 lg:inset-4 z-20`, focus-trap, return-focus, escape-to-close) with three new tabs:

- **Personas tab**: full grid of personas, search, NSFW filter respecting sanitised mode. (Mostly exists — `UserModal` already routes to persona overview.)
- **Projects tab**: list of projects, search by name, filter by pinned/all, click-to-open a project's detail view.
- **History tab**: already exists with date grouping (Today / Yesterday / This Week / This Month / Month YYYY) and persona dropdown filter. Extend with optional project filter (single-select dropdown — see memory `feedback_filter_controls`).

The user has expressed preference for adding tabs to `UserModal` over standing up new modal shells — so we follow that.

### 6.4 Project detail view

When the user clicks a project in the sidebar or modal, what do they see? Two options worth discussing during brainstorming:

- **Option A — modal pane.** A second-level modal layer inside `UserModal`'s Projects tab: list on the left, detail on the right. Files / artefacts / sessions as inner tabs. Pros: reuses focus-trap; Cons: nested-modal cognitive load.
- **Option B — dedicated route `/projects/{id}`.** Full-page view that replaces the chat area. Sidebar still visible. Pros: more screen real-estate, comfortable for the files browser; Cons: needs its own layout, bookmarkable URL is double-edged (privacy on shared screens).

Recommendation lean: **Option B**, because the files/artefacts grid wants real estate and a full URL handle is genuinely useful for a "click on project → see everything" workflow.

### 6.5 Emoji picker — second LRU

Replicate the existing pattern with new file paths, no shared logic:

- New store `frontend/src/features/projects/recentProjectEmojisStore.ts` — same shape as `recentEmojisStore.ts`.
- New backend field on `User`: `recent_project_emojis: list[str]`.
- New event `Topics.USER_RECENT_PROJECT_EMOJIS_UPDATED`.
- New endpoint patches the user document.
- The picker component takes a `recentEmojisSource: 'message' | 'project'` prop and reads the corresponding store.

Deliberately separate stores. No abstraction layer over the two. Two LRUs aren't enough to justify a generic mechanism.

### 6.6 Drag and drop

The existing sidebar uses `@dnd-kit` for persona reordering and chat-session reordering. Extending to:

- Reorder pinned projects within their zone: same pattern.
- Drop a chat onto a project to assign it: new cross-zone drop. Requires a `DroppableZone` per project? Or a single drop-target on the Projects label that opens a "pick project" mini menu? The latter is simpler and more discoverable on desktop.
- Drop a chat outside any project to unassign: drag onto the History label.

Drag-to-assign is a desktop-only convenience. Mobile uses a context menu on the chat tile.

### 6.7 NSFW filtering

Single source of truth: `useSanitisedMode().isSanitised`. Filtering happens upstream in `AppLayout.tsx:83–96` (where personas and sessions are filtered before being passed to `Sidebar`). We add a parallel `filteredProjects = useMemo(...)` line. No new mechanism, just one more field.

The `HistoryTab`'s server-side `exclude_persona_ids` argument has a new sibling `exclude_project_ids` for searches in sanitised mode. Same pattern.

### 6.8 Mobile

- New mobile sub-view: `'projects'` in the `MobileView` union at `Sidebar.tsx:213`.
- `MobileMainView` gets a third row "Projects" between Personas and History.
- Tapping it slides the second panel in, showing a project list with a back button and a search input.
- Tapping a project navigates to its detail route (option B above) and closes the drawer.
- The aggregated files view inside a project on mobile is a vertically stacked tab control (single column), not a grid.

---

## 7. Library merge — semantics & edge cases

`unique(persona_libraries ∪ project_libraries ∪ session_libraries)`. Order does not matter for retrieval — knowledge search treats it as a set. But for **display** in the UI ("which libraries are active in this chat?"), we deduplicate while preserving a sensible order: persona first, then project, then session-additions, alphabetical within each group.

Edge cases to discuss in brainstorm:

- **Library deleted while chat is in flight.** Existing cascade in `knowledge.cascade_delete_library` removes the library from personas and sessions. Add `project.remove_library_from_all_projects` as a parallel. The orchestrator already re-reads library IDs per inference, so a mid-conversation removal becomes effective on the next turn.
- **Project's NSFW library used in non-NSFW persona.** Sanitised mode is **client-side display only** — backend retrieval ignores it. So a sanitised user who has an NSFW project library subscribed will still get NSFW knowledge in retrieval results. **Open question §10.4.**
- **Project removed while a chat lives in it.** Cascade sets `project_id = None`; chat reverts to the global history. Library merge from project drops away on the next inference. Acceptable.

---

## 8. Migration story (beta-safe)

We are past the 2026-04-15 wipe cutoff (memory: `project_beta_release`). Every change must be backwards-compatible reads or a one-shot migration script. Specifically:

| Change | Strategy |
|---|---|
| New field `project_id` on `chat_sessions` | Default `None`. Reads use `doc.get("project_id")`. No migration needed. |
| New field `knowledge_library_ids` on `projects` | Default `[]`. Reads use `doc.get("knowledge_library_ids", [])`. No migration. |
| New compound index `[user_id, project_id, updated_at desc]` | Idempotent `create_index` at module init. |
| New user field `recent_project_emojis` | Default `[]`. Frontend reads via `?? []`. No migration. |
| New topics | Additive, no impact on existing subscribers. |
| Removing the inline history search input | Frontend-only — no data implication. |

**No migration script needed.** This is the cleanest possible upgrade path. Every change is additive; every read is defended.

---

## 9. Out of scope (deliberate)

These are tempting but not part of this round. Each gets its own brief later if we decide to do it.

- **Project-level custom system prompt** (Claude.ai's "Project instructions"). Personas already cover this. Adding a second prompt source per chat invites composition rules that nobody enjoys.
- **Project-level memory.** Memory today is per-persona. Stays that way.
- **Project sharing / multi-user projects.** Single-user app for the foreseeable.
- **Projects-in-projects (nesting).** Flat, one level deep.
- **Cross-project file deduplication.** Each project shows its own files; if the same file is uploaded to two chats in two projects, it appears twice. Acceptable.
- **Project archiving.** Delete is delete. If users complain, we add archive later.
- **Project templates.** No.
- **Server-side enforcement of NSFW gating.** Sanitised mode remains a client-side UX filter. The data is not security-classified.

---

## 10. Open questions for brainstorming

These are the ones I want to argue through before any plan is written.

1. **Project description field.** Worth having? Where does it surface — on hover in the sidebar, only in the detail view, or in the modal list? Adds a small writing burden at create time and an easy one to leave empty. Lean: yes, small textarea, optional, displayed on hover and in the detail view.
2. **Auto-create-on-drop.** When a user drags a chat to a "create project" target with a name, do we auto-create + assign in one step? Or always two steps? Lean: two steps, predictable.
3. **Pin limits.** Three zones at 33% each is a UX promise — but if a user pins 40 projects, the zone scrolls internally rather than overflowing the parent. Do we cap pin count (say, 12 per zone) and refuse the 13th, or let it scroll inside the zone? Lean: scroll inside the zone, no hard limit, but show a hint.
4. **Sanitised mode and library NSFW leak.** §7 edge case: an NSFW library subscribed via a project will still inject content into a sanitised-mode chat. Do we filter library results by `library.nsfw` in sanitised mode at retrieval time? That would be the only place sanitised mode crosses into backend behaviour. Lean: yes, but as a separate brief — orthogonal to this feature.
5. **Project detail = page or nested modal.** §6.4. Lean: page route.
6. **Move-chat UX on desktop.** §6.6. Drag onto a per-project zone vs drag onto a generic "pick project" target. Lean: generic target, then mini-picker.
7. **History modal: should "All chats" view show project chats too, with a project tag?** Or strict "chats outside projects only"? The brief currently says hide. But a power user might want one-stop search. Lean: default hide; toggle "include project chats" with a tag column.
8. **Files view: include user-uploaded vs LLM artefacts in one merged list, or two tabs?** The data model splits them. The user mental model might too ("things I uploaded" vs "things the AI made for me"). Lean: two tabs, with counts.
9. **Display order of pinned items: drag-reorder, or auto by recency?** Personas use manual drag-reorder today. Project pinning should match. Lean: match.
10. **Empty state.** A new install has zero projects. The Projects sidebar zone collapses to "No pinned projects · Create one →". Acceptable wording but worth a UX pass.

---

## 11. Reference index — files to read on first acquaintance

Backend:
- `backend/modules/project/` — existing skeleton.
- `backend/modules/chat/_repository.py:271–287` — `list_sessions` aggregation pipeline (extension target).
- `backend/modules/chat/_orchestrator.py:189–256` — library-id closure (merge target).
- `backend/modules/knowledge/_retrieval.py:15–26` — `effective_ids` set merge.
- `backend/modules/persona/__init__.py:78` — public API surface to mirror.
- `backend/modules/storage/_repository.py:129–143` — file metadata schema.
- `backend/modules/artefact/_repository.py` — artefact schema (note: `_id` is `ObjectId`, not UUID).
- `shared/dtos/project.py` — DTOs and `_Unset` sentinel pattern.
- `shared/topics.py:116` — existing project topics.
- `backend/modules/chat/__init__.py:44` — already-anticipates-`project_id` comment.

Frontend:
- `frontend/src/app/components/sidebar/Sidebar.tsx:161, 211, 213, 525, 926, 999` — disabled-Projects markers and the inline 8-session slice.
- `frontend/src/app/components/user-modal/UserModal.tsx:267` — disabled Projects tab.
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — date-grouping algorithm and OPTION_STYLE pattern to copy.
- `frontend/src/app/layouts/AppLayout.tsx:83–96` — central NSFW filtering point.
- `frontend/src/features/chat/recentEmojisStore.ts` — LRU pattern to duplicate.
- `frontend/src/core/hooks/useViewport.ts:63` — `lg`-breakpoint definition.
- `frontend/src/core/hooks/useChatSessions.ts` — Zustand+EventBus pattern to copy for `useProjects`.
- `frontend/src/core/websocket/eventBus.ts` — event subscription mechanism.

---

## 12. Conventions reminders

- Module boundaries: project module talks to other modules only via public APIs (`__init__.py`). The library-merge in `_orchestrator.py` calls `project_service.get_library_ids(...)` — never reaches into `project._repository`.
- All cross-module DTOs and topics live in `shared/`. No magic strings.
- Every state change emits a WebSocket event. The frontend never polls.
- Use the `_Unset` sentinel pattern in PATCH DTOs for nullable fields (already implemented for project emoji).
- Migrations are idempotent and gated by a marker in the `_migrations` collection — but for this feature we don't need any (see §8).
- British English in code, comments, identifiers.

---

## 13. How to use this brief

1. Open a fresh Claude Code session in the chatsune repo.
2. Hand it this file as the conversation opener: *"Here's the brief — let's brainstorm before planning."*
3. Walk through §10 first; settle the open questions.
4. Then invoke `superpowers:brainstorming` to surface anything missed.
5. Then `superpowers:writing-plans` to draft the implementation plan in `devdocs/plans/`.
6. Then `superpowers:using-git-worktrees` + subagent-driven execution.

The brief is not a plan. It is the input to a brainstorm.
