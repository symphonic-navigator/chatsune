# Mindspace (Projects) — Design

**Date:** 2026-05-04
**Status:** Pending review
**Scope:** Backend (`project`, `chat`, `persona`, `storage`, `artefact`, `image`, `knowledge`) + Frontend (sidebar Projects-zone, chat top-bar switcher, project-detail-overlay, user-modal `ProjectsTab`, persona overview default-project selector).
**Replaces:** `PROJECTS-FEATURE.md` (to be removed in a follow-up commit after this spec is approved).
**Companion:** `devdocs/specs/2026-05-03-sidebar-redesign-projects-prep-design.md` (sidebar groundwork already shipped — `ZoneSection zone="projects"`, hidden Projects nav entry, Projects flyout slot all reserved).

---

## 1. Vision — "Mindspace"

Chatsune positions Projects as a second axis of organisation orthogonal to personas. The product framing is **Mindspace**: when the user is inside a project chat, their head should be free for that one thing. The emoji pill in the chat top-bar is the visual anchor that tells them which mindspace they are in.

Mindspace is a framing, not extra UI machinery. The features that make it honest are:

- A project bundles chats and, indirectly, all uploads, artefacts, and images created in those chats.
- A project carries its own set of knowledge libraries; persona-level libraries are merged with project-level libraries at retrieval time (`unique(persona ∪ project ∪ session)`).
- A project carries an emoji and an optional description.
- A project may have zero or more "default personas" — personas configured to land in this project when a new chat is started from a neutral trigger point.
- A project can be flagged NSFW and is then hidden across all surfaces in sanitised mode.

Two unique wins over Claude.ai / ChatGPT / Grok:
1. Reusable knowledge libraries shared between personas and projects.
2. NSFW-aware sanitised mode that filters the project surface.

---

## 2. Feature scope (user-facing)

1. **Project = container for chats.** A chat session belongs to at most one project, or to none. Reassignment is allowed at any time.
2. **Indirect aggregation.** A project surfaces all uploads, artefacts, and images from its member chats — no separate "project files" silo.
3. **Optional emoji per project**, picked via the existing emoji picker, with a **separate LRU** from the chat-message emoji picker.
4. **Knowledge library assignment per project**, merged unique with persona libraries at retrieval time.
5. **Default-project per persona.** A persona may have one default project; new chats started from neutral trigger points (sidebar pin click, persona overview, persona modal) auto-assign to that project. From context-bound trigger points (project-detail-overlay personas tab, project-detail-overlay "new chat here") the surrounding project always wins.
6. **In-chat project switcher** in the chat top-bar (right side, top row): `[emoji][project name][▾]`. Click on `[emoji][project name]` opens the Project-Detail-Overlay; click on `[▾]` opens a picker (desktop dropdown / mobile fullscreen overlay) with: "— No project", project list (auto-sorted), "+ Create new project…".
7. **Project-Detail-Overlay** with six tabs: Overview, Personas, Chats, Uploads, Artefacts, Images. Modal pattern, analogous to the existing Personas-Detail-Overlay.
8. **Sidebar Projects-zone** between Personas and History (slot already reserved).
9. **Hidden from default history.** Chats inside a project no longer appear in the global history list by default; an opt-in toggle "Include project chats" surfaces them with a project pill.
10. **NSFW flag per project.** Projects can be marked NSFW; in sanitised mode they are filtered from sidebar, switcher picker, ProjectsTab, persona-tab, and history toggle.
11. **Mobile parity.** All flows mirror to mobile: switcher fullscreen-overlay (analogous to "start new chat"), project-detail-overlay full-screen, single-column listings.

---

## 3. Existing scaffolding

The repository already contains a deliberately-disabled Projects skeleton.

### Backend

- **Module:** `backend/modules/project/` with `_repository.py`, `_handlers.py`, `_models.py`, public API in `__init__.py`. Wired up in `backend/main.py:63`.
- **DTOs:** `shared/dtos/project.py` with `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto`, plus `_Unset` sentinel for PATCH bodies.
- **Topics:** `Topics.PROJECT_CREATED`, `Topics.PROJECT_UPDATED`, `Topics.PROJECT_DELETED` in `shared/topics.py:116`.
- **Project doc fields today:** `id`, `user_id`, `name`, `emoji`, `nsfw`, `pinned`, `display_order`, `created_at`, `updated_at`. (`display_order` is now legacy — see §4.1.)
- **Chat session export allow-list already accommodates `project_id`** — comment at `backend/modules/chat/__init__.py:44`.

### Frontend

- **Sidebar groundwork shipped** — `ZoneSection zone="projects"` reserved at `Sidebar.tsx:705`, hidden Projects nav entry at `Sidebar.tsx:369` and `Sidebar.tsx:521`, `flyoutTab` union widened at `Sidebar.tsx:120`.
- **`UserModal/ProjectsTab.tsx`** exists as stub.
- **Empty state copy** `'No projects yet · Create one →'` already wired (Sidebar.tsx:710).
- **Greenfield additions still to come:** `useProjects` hook, `projectsApi.ts`, `recentProjectEmojisStore`, project-related event subscriptions, project-detail-overlay component tree.

---

## 4. Data model

All changes additive; reads default-defended; **no migration required** (per `project_beta_release` memory).

### 4.1 `projects` collection — extended

```python
class ProjectDocument:
    id: str                                  # existing UUID
    user_id: str                              # existing
    name: str                                 # existing
    emoji: str | None                         # existing
    nsfw: bool = False                        # existing
    pinned: bool = False                      # existing
    knowledge_library_ids: list[str] = []     # NEW
    description: str | None = None            # NEW
    created_at: datetime                      # existing
    updated_at: datetime                      # existing
```

`display_order` is dropped from the new schema. Old documents that still carry the field are read-tolerated (ignored). Auto-sort is `pinned desc, updated_at desc` everywhere — there is no manual reorder UI.

### 4.2 `chat_sessions` collection — new field

```python
project_id: str | None = None                 # NEW
```

Read everywhere via `doc.get("project_id")`.

### 4.3 `personas` collection — new field

```python
default_project_id: str | None = None         # NEW
```

`None` means the persona has no default project. Mutated through the existing persona PATCH endpoint.

### 4.4 `users` collection — new field

```python
recent_project_emojis: list[str] = []         # NEW
```

Separate LRU from the chat-message emoji picker.

### 4.5 Indexes (idempotent in `init_indexes`)

| Collection | Index | Purpose |
|---|---|---|
| `chat_sessions` | `[user_id, project_id, updated_at desc]` | "Sessions in project X" + "Sessions outside any project" |
| `projects` | `[user_id, pinned desc, updated_at desc]` | Sidebar listing |
| `personas` | sparse `[user_id, default_project_id]` | "Personas with default in project P" |

Existing `chat_sessions [user_id, updated_at desc]` is retained.

### 4.6 Cascade rules

| Action | Effect |
|---|---|
| Delete project (**safe-delete**, default) | `chat_sessions.project_id = null` for all member sessions; `personas.default_project_id = null` for all personas pointing at it |
| Delete project (**full-purge**) | Cascade-delete all member sessions (and their messages, uploads, artefacts, images); `personas.default_project_id = null`; **memory and journal entries are NOT rolled back** (they are persona-owned); libraries untouched |
| Library deleted globally | `knowledge.cascade_delete_library` additionally calls `project.remove_library_from_all_projects(library_id)` |
| Persona deleted | No cascade on project; persona is gone |
| Chat removed from project | `chat_sessions.project_id = null`; chat reappears in global history |

---

## 5. Backend architecture

### 5.1 Project module — public API

```python
# backend/modules/project/__init__.py
async def get_project(project_id, user_id) -> ProjectDto | None
async def list_projects_for_user(user_id) -> list[ProjectDto]
async def get_library_ids(project_id, user_id) -> list[str]
async def list_project_ids_for_user(user_id) -> list[str]
async def remove_library_from_all_projects(library_id) -> None
async def cascade_delete_project(project_id, user_id, *, purge_data: bool) -> None
async def get_usage_counts(project_id, user_id) -> ProjectUsageDto
   # returns {chat_count, upload_count, artefact_count, image_count}
   # used by the delete-modal to show what would be purged
```

### 5.2 Chat module — additions

```python
# Document
project_id: str | None = None

# Public API
async def list_sessions(user_id, exclude_in_projects: bool = True) -> list[...]
   # Default behaviour for global history changes to "exclude project chats"
async def list_sessions_for_project(user_id, project_id) -> list[...]
async def list_session_ids_for_project(project_id, user_id) -> list[str]
   # Used by storage / artefact / image modules for project-filtered queries
```

### 5.3 Persona module — additions

```python
# Document
default_project_id: str | None = None
```

Mutation runs through the existing persona PATCH endpoint. The `_Unset` sentinel pattern is used so that callers can set, clear, or leave the field untouched. Triggering a change via the project-detail-overlay personas tab still ends up as a `PATCH /api/personas/{id}` from the frontend — single uniform flow.

### 5.4 REST endpoints

```
GET    /api/projects                              list (pinned desc, updated_at desc)
POST   /api/projects                              create
GET    /api/projects/{id}                         single
GET    /api/projects/{id}?include_usage=true      single + usage counts (for delete modal)
PATCH  /api/projects/{id}                         name, emoji, nsfw, description, knowledge_library_ids
DELETE /api/projects/{id}?purge_data=true|false   default false = safe-delete
PATCH  /api/projects/{id}/pinned                  dedicated, fires PROJECT_PINNED_UPDATED

PATCH  /api/chat/sessions/{id}/project            body {"project_id": str | null}

# project_id query-param added to existing tab endpoints (replaces the
# aggregated /api/projects/{id}/files endpoint from the original brief):
GET    /api/chat/sessions?project_id={id}         HistoryTab in project-overlay
GET    /api/storage/files?project_id={id}         UploadsTab in project-overlay
GET    /api/artefact?project_id={id}              ArtefactsTab in project-overlay
GET    /api/images?project_id={id}                ImagesTab in project-overlay
```

Deliberate omissions versus the original brief:
- **No** `PUT /api/projects/{id}` (full replace) — PATCH suffices.
- **No** `PATCH /api/projects/reorder` — auto-sort by `pinned + updated_at`.
- **No** dedicated `GET/PUT /api/projects/{id}/knowledge` — `knowledge_library_ids` rides the regular PATCH.
- **No** aggregated `GET /api/projects/{id}/files` — the existing tab components are reused with a `projectFilter` prop and call their own module endpoints.

### 5.5 Library merge — load-bearing change

In `backend/modules/chat/_orchestrator.py:run_inference`, after loading session and persona:

```python
project_lib_ids: list[str] = []
if session.get("project_id"):
    project_lib_ids = await project_service.get_library_ids(session["project_id"], user_id)
```

`_make_tool_executor` accepts the third source; `_retrieval.search` does:

```python
effective_ids = list(set(persona_library_ids + session_library_ids + project_library_ids))
```

The knowledge module remains unaware of the new source — composition lives in the orchestrator, which respects module boundaries. The merge is dynamic per inference, no cache, so a library added to or removed from the project becomes effective on the next turn.

### 5.6 Cross-module project-filtering

Storage / artefact / image modules accept the `project_id` query param. Internally they ask `chat.list_session_ids_for_project(project_id, user_id)` and then run their own `$in` lookup against `session_id`. No internal-import shortcuts; no module needs to know about the project schema.

### 5.7 New topics in `shared/topics.py`

```python
PROJECT_PINNED_UPDATED              = "project.pinned.updated"
CHAT_SESSION_PROJECT_UPDATED        = "chat.session.project.updated"
USER_RECENT_PROJECT_EMOJIS_UPDATED  = "user.recent_project_emojis.updated"
```

Existing: `PROJECT_CREATED`, `PROJECT_UPDATED`, `PROJECT_DELETED`.

`default_project_id` changes on a persona ride `PERSONA_UPDATED` (no dedicated topic).

---

## 6. Frontend architecture

### 6.1 Sidebar Projects-zone

`ZoneSection zone="projects"` is already wired (Sidebar.tsx:705). Activation:

- **Position:** Personas → Projects → History
- **Content:** pinned projects, sorted `pinned desc, updated_at desc`
- **Per item:** emoji + name; click opens Project-Detail-Overlay
- **Empty state:** "No pinned projects · Create one →" (click → Project-Create-Modal)
- **"Projects →" trigger:** opens `UserModal/ProjectsTab`
- **Context menu** (right-click desktop / long-press mobile): Pin/Unpin · Edit · Delete · Open

Mobile: new "Projects" entry between Personas and History in `MobileMainView`.

### 6.2 Chat top-bar — In-chat project switcher

Position: top row of the chat top-bar, right side. Layout:

```
[emoji][Project Name] [▾]    ← project assigned
[—] [No project]      [▾]    ← unassigned
```

- `[emoji][name]` clickable → opens Project-Detail-Overlay
- `[▾]` opens picker

**Picker contents (always in this order):**
1. "— No project" (`PATCH /api/chat/sessions/{id}/project {project_id: null}`)
2. Search input (always present, placeholder *"Search projects…"*)
3. Project list — auto-sorted, sanitised-filtered
4. "+ Create new project…" — opens Project-Create-Modal; on success auto-assigns the active session

**Plattform:** desktop dropdown, mobile fullscreen overlay analogous to the "Start new chat" flow.

### 6.3 Persona Overview — Default-project selector

In the Personas-Detail-Overlay → Overview tab, a new field:

```
Default project    [—  ▾]      ← or [✨ Star Trek Fan Fiction  ▾]
```

- Picker analogous to the chat switcher
- Mutation: persona PATCH with `default_project_id`
- Event: `PERSONA_UPDATED`

### 6.4 `UserModal/ProjectsTab`

Replaces the current stub. Layout:

```
[Search projects…]                          [+ New Project]
─────────────────────────────────────────────────────────────
[✨] Star Trek Fan Fiction       pinned · updated 2d ago
     "Fanfic with Mr. Worf about romulan diplomacy."
[🎼] Music Theory Notes          updated 5d ago
…
```

- Client-side search by name
- Filter pill: all / pinned only
- Per item: emoji + name + truncated description + last-updated; click → Project-Detail-Overlay
- "+ New Project" → Project-Create-Modal (single uniform form, all fields except name optional)

**Project-Create-Modal fields:** Name (required), Emoji (optional, picker with `recent_project_emojis` LRU), Description (optional, textarea), NSFW (toggle, default off), Knowledge Libraries (multi-select, optional).

### 6.5 Project-Detail-Overlay (six tabs)

Layout pattern: analogous to the existing Personas-Detail-Overlay. Tab strip on top, content beneath, close via X / Escape / click-outside.

#### Tab 1: Overview

```
        ┌─────────┐
        │   ✨    │   ← large emoji (picker with recent_project_emojis-LRU)
        └─────────┘
        [Project Name]                     ← inline-edit, save on blur

Description
[ Working on a fanfic with Mr. Worf about    ]
[ romulan diplomacy.                          ]   ← textarea, inline-edit

NSFW              [⨉ off]
Knowledge libraries  [Star Trek ✕] [Romulans ✕]   [+ Add library…]

─────────────── Danger Zone ───────────────
[ Delete Project ]                           ← opens delete modal §9
```

#### Tab 2: Personas

```
Default personas in this project              [+ Add persona]
─────────────────────────────────────────────────────────────
[👤] Mr. Worf
     Klingon security officer, gruff, formal.
     [Start chat here]   [Remove from project]

[👤] Friedrich Schiller
     Sci-fi-translated playwright, philosophical.
     [Start chat here]   [Remove from project]
```

- Listed: personas with `default_project_id == this_project`
- Sort: alphabetical by persona name
- `[Start chat here]` — context-bound trigger: creates a new session with `project_id = this_project`, closes overlay, opens chat
- `[Remove from project]` — persona PATCH with `default_project_id = null`
- `[+ Add persona]` — opens persona picker (sanitised-filtered); if the chosen persona already has a different default project, confirmation: *"Mr. Worf is currently default in 'TNG Episodes'. Switch?"*

#### Tab 3: Chats — `<HistoryTab projectFilter={projectId} />`

Reuses the existing `HistoryTab` component with a `projectFilter` prop. Same layout (search, date-bucket grouping, pin star, persona avatar, title, last-updated). Click opens chat. Context-menu per item: Pin/Unpin · Move to other project · Remove from project · Delete chat.

#### Tab 4: Uploads — `<UploadsTab projectFilter={projectId} />`

Same component as in `UserModal`, with `projectFilter` prop. Filename / size / upload-date / "↗ chat" link. Filter by file-type. Mobile = single-column.

#### Tab 5: Artefacts — `<ArtefactsTab projectFilter={projectId} />`

Same component as in `UserModal`, with `projectFilter` prop. Title / type / created-date / "↗ chat" link. Filter by type.

#### Tab 6: Images — `<ImagesTab projectFilter={projectId} />`

Same component as in `UserModal`, with `projectFilter` prop. Grid (desktop) / single-column (mobile). Lightbox on click, with source-chat link.

### 6.6 Mobile

- New `MobileView` discriminator: `'projects'` in `Sidebar.tsx:213`
- `MobileMainView` gets a "Projects" row between Personas and History
- Tapping a project opens the Project-Detail-Overlay full-screen
- Tabs render as a horizontal scroll-strip under the project title
- Files / artefacts / images render single-column

### 6.7 NSFW filtering

Single source of truth: `useSanitisedMode().isSanitised` (already used for personas).

Filtering point: `AppLayout.tsx:83-96` (where personas and sessions are filtered before being passed downstream). Add a parallel `filteredProjects = useMemo(...)` and `filteredPersonasByProject` selector.

| Surface | Behaviour in sanitised mode |
|---|---|
| Sidebar Projects-zone | NSFW-projects hidden |
| In-chat switcher picker | NSFW-projects hidden |
| `ProjectsTab` (UserModal) | NSFW-projects hidden |
| Project-detail-overlay | reachable via active chat only; not navigable via list |
| Personas-tab in project-overlay | NSFW-personas hidden in list and "+ Add" picker |
| `HistoryTab` with "Include project chats" | chats from NSFW-projects hidden |

**Active chat in NSFW-project, user toggles sanitised on:** chat stays open, top-bar switcher continues to display the project. Rationale: sanitised filters *discoverability*, not *active visibility*. "What is already open stays open."

### 6.8 Project emoji LRU

New store `frontend/src/features/projects/recentProjectEmojisStore.ts`, mirroring `recentEmojisStore.ts`. Backend persists `recent_project_emojis` on the user document. `Topics.USER_RECENT_PROJECT_EMOJIS_UPDATED` notifies other tabs. The emoji picker component takes a `recentEmojisSource: 'message' | 'project'` prop.

### 6.9 `UserModal/HistoryTab` — "Include project chats" toggle

Default behaviour changes: project-bound chats are hidden from the UserModal HistoryTab. A new toggle "Include project chats" surfaces them; when on, each project chat carries a small project pill (`[emoji] Project Name`) next to its title for instant recognition. Toggle state persists in `safeLocalStorage` (consistent with the existing persona-filter persistence in HistoryTab).

The same component reused in the project-detail-overlay (Tab 3) ignores the toggle entirely — there it is implicitly "show this project's chats only", driven by the `projectFilter` prop.

---

## 7. Library merge — semantics & edge cases

`unique(persona_libraries ∪ project_libraries ∪ session_libraries)`. Order does not matter for retrieval (treated as a set). For the "active libraries in this chat" UI display, we deduplicate while preserving a sensible order: persona first, then project, then session-additions; alphabetical within each group.

### Edge cases

- **Library deleted while chat is in flight.** `knowledge.cascade_delete_library` removes the library from personas, sessions, and projects. The orchestrator re-reads library IDs per inference, so a mid-conversation removal becomes effective on the next turn.
- **Project removed while chat is in flight.** Cascade sets `project_id = null`; chat reverts to global history. Library merge from project drops away on next inference. Acceptable.
- **NSFW-library via project in sanitised chat.** Out-of-scope for Mindspace — orthogonal brief, see §13.

---

## 8. NSFW & sanitised mode

See §6.7 for the per-surface table. Two architectural notes:

- **Sanitised mode remains client-side display filter.** Backend retrieval is not NSFW-aware. The "NSFW-library leak" question is out-of-scope for Mindspace.
- **`AppLayout.tsx`** is the single filtering hook for personas, sessions, and now projects. Adding any surface that lists projects requires consuming `filteredProjects` or applying the same predicate.

---

## 9. Delete flow

Single-modal pattern with a safe default and an explicit checkbox for the destructive variant.

```
Delete project "Star Trek Fan Fiction"
─────────────────────────────────────────

After deletion, this project will be removed.
Its 14 chats will return to your global history.

[ ] Also delete all data permanently
    14 chats · 8 uploads · 23 artefacts · 6 images
    This cannot be undone.

                              [Cancel]   [Delete project]
```

- Counts come from `GET /api/projects/{id}?include_usage=true`
- Default checkbox state: off → `DELETE /api/projects/{id}?purge_data=false`
- Checkbox on: button label switches to *"Delete project + all data"*, style turns destructive-red → `DELETE /api/projects/{id}?purge_data=true`
- Submit emits `PROJECT_DELETED` plus, depending on mode:
  - Safe-delete: `CHAT_SESSION_PROJECT_UPDATED` per detached session, `PERSONA_UPDATED` per persona that had this project as default
  - Full-purge: cascading delete events from each affected module (chat / storage / artefact / image), plus `PERSONA_UPDATED` per affected persona
- **Memory and journal are not rolled back** (persona-owned, decoupled from chat lifecycle once distilled)

---

## 10. Migration

**No migration script required.** Every change is additive with sensible defaults; every read is defended.

| Change | Strategy |
|---|---|
| `project_id` on `chat_sessions` | Default `None`, `doc.get("project_id")` |
| `knowledge_library_ids` on `projects` | Default `[]` |
| `description` on `projects` | Default `None` |
| `default_project_id` on `personas` | Default `None` |
| `recent_project_emojis` on `users` | Default `[]` |
| New compound index `[user_id, project_id, updated_at desc]` | Idempotent `create_index` at module init |
| New topics | Additive |
| Legacy `display_order` on `projects` | Read-tolerated (ignored), no rewrite |

The upgrade path is exercised against a database snapshot containing pre-Mindspace project documents — see §14.

---

## 11. Module boundaries

Reminder of the hard rules — no internal-import shortcuts.

- The `project` module is the only public surface for project data.
- The chat orchestrator calls `project_service.get_library_ids(...)`, never `project._repository`.
- Storage / artefact / image modules call `chat.list_session_ids_for_project(...)` for project-filtered queries; they never query the projects collection directly.
- Persona mutations to `default_project_id` flow through the persona module's PATCH endpoint, even when triggered from the project-detail-overlay personas tab.
- All cross-module DTOs and topics live in `shared/`. No magic strings.

---

## 12. Brief §10 — resolution

Original `PROJECTS-FEATURE.md` left ten open questions. Resolutions:

| § | Question | Resolution |
|---|---|---|
| 10.1 | Project description? | **Yes**, in Overview tab; not in sidebar hover (Mindspace stillness) |
| 10.2 | Auto-create-on-drop? | **Obsolete** — D&D removed |
| 10.3 | Pin limits? | **No hard cap** — auto-sort by `pinned + updated_at`, scroll inside zone |
| 10.4 | NSFW-library leak in sanitised | **Out-of-scope** for Mindspace — separate brief |
| 10.5 | Detail page or modal | **Modal** — Project-Detail-Overlay analogous to Personas |
| 10.6 | Move-chat UX | **Context menu** — D&D removed |
| 10.7 | History "include project chats"? | **Toggle, default hide**, with project pill per item |
| 10.8 | Files view: one tab or many | **Three tabs** (Uploads / Artefacts / Images), reusing UserModal components with `projectFilter` |
| 10.9 | Display order | **Auto by `pinned + updated_at`** — no manual reorder |
| 10.10 | Empty state | "No pinned projects · Create one →" |

---

## 13. Out-of-scope

Inherited from `PROJECTS-FEATURE.md` §9, plus Mindspace-specific exclusions.

- **Project-level system prompt** (Claude.ai's "Project instructions"). Personas already cover this.
- **Project-level memory.** Memory is per-persona.
- **Project sharing / multi-user projects.** Single-user app.
- **Projects-in-projects.** Flat, one level.
- **Cross-project file deduplication.**
- **Project archiving.** Delete is delete.
- **Project templates.**
- **Server-side enforcement of NSFW gating.** Sanitised remains client-side display filter.
- **Drag-and-drop reactivation.** D&D is removed everywhere; Mindspace will not re-introduce it.
- **Persona multi-default.** A persona has zero or one default project, not many.
- **Sidebar refactor beyond inserting the Projects-zone.** Already shipped as a separate spec.

---

## 14. Manual verification

Before merging, the implementer runs the following on a real device against a database snapshot that contains both pre-Mindspace and freshly-written documents.

### Backend / data

1. **Backwards compatibility:** Open a chat session whose document predates the Mindspace migration (no `project_id` field). Verify the chat loads, history lists it, and library merge works (no project libraries injected).
2. **Library merge:** Create a project with library "Star Trek". Persona "Worf" already subscribes to library "Klingons". Start a chat with Worf in the project. Trigger a knowledge-tool call. Verify the retrieval set is `{Star Trek, Klingons}` (de-duplicated), checked via backend logs (`effective_ids`).
3. **Cascade safe-delete:** Delete a project with safe-delete. Verify all member sessions have `project_id == null` and reappear in global history; verify personas with `default_project_id` pointing at it now show `null`; verify the project itself is gone.
4. **Cascade full-purge:** Delete a project with `purge_data=true`. Verify the member sessions, their messages, uploads, artefacts, and images are all gone. Verify personas only lose their `default_project_id`. Verify `recent_project_emojis` and the persona's library list are untouched.
5. **Library cascade:** Delete a library that is referenced by both a persona and a project. Verify the library disappears from both `persona.knowledge_library_ids` and `project.knowledge_library_ids`.

### Frontend / UX

6. **Sidebar Projects-zone:** Pin a project. Verify it appears in the sidebar between Personas and History. Unpin via context menu. Verify it disappears.
7. **In-chat switcher (desktop):** Open a chat. Switch its project via the `[▾]` dropdown to "No project", to a different project, and via "+ Create new project…". Verify each PATCH lands and the WebSocket event updates the top-bar emoji.
8. **In-chat switcher (mobile):** Same scenarios on a phone. Verify the picker is a fullscreen overlay (analogous to "Start new chat") and not a dropdown.
9. **Persona default-project flow:** Set "Worf"'s default project to "Star Trek Fan Fiction" via the Personas overview. Click on Worf in the sidebar from a neutral context (not from any project view). Verify the new chat lands in "Star Trek Fan Fiction".
10. **Personas-tab context trigger:** Open the Project-Detail-Overlay → Personas tab. Click "[Start chat here]" on a persona that has a different default project. Verify the new chat is in the *current* project (context wins, not persona default).
11. **Adding a persona that's already default elsewhere:** From Project-Detail-Overlay → Personas → "+ Add persona", pick a persona currently default in another project. Verify the confirmation dialog appears and that confirming switches the persona's default.
12. **Reused tab components:** Verify that `HistoryTab`, `UploadsTab`, `ArtefactsTab`, `ImagesTab` render correctly with `projectFilter` set (in the project-overlay) and unset (in the user-modal). Same UI, different data.
13. **HistoryTab toggle:** In UserModal HistoryTab, verify project chats are hidden by default. Toggle "Include project chats" on; verify project chats appear with a `[emoji] Name` pill next to the title. Toggle state persists across reloads.
14. **Sanitised mode filtering:** Mark a project NSFW. Toggle sanitised on. Verify the project is hidden from sidebar, switcher picker, ProjectsTab, persona-tab "+ Add" picker, and HistoryTab even with "Include project chats" on.
15. **Sanitised + active NSFW chat:** Open a chat in an NSFW project, then toggle sanitised on. Verify the chat stays open and the switcher continues to show the project.
16. **Delete modal counts:** Open the delete modal on a project with non-trivial data. Verify the counts (chats / uploads / artefacts / images) are accurate.
17. **Project emoji LRU:** Pick a project emoji. Pick a chat-message emoji. Open the project emoji picker again. Verify the project-LRU shows the project emoji at the top and not the chat-message one.
18. **Empty state:** Fresh user with no pinned projects. Verify the sidebar Projects-zone shows "No pinned projects · Create one →" and clicking opens the create modal.

---

## 15. Reference index — files to read on first acquaintance

### Backend

- `backend/modules/project/` — existing skeleton.
- `backend/modules/chat/_repository.py` — `list_sessions` aggregation pipeline (extension target).
- `backend/modules/chat/_orchestrator.py` — library-id closure (merge target).
- `backend/modules/knowledge/_retrieval.py` — `effective_ids` set merge.
- `backend/modules/persona/__init__.py` — public API surface to mirror.
- `backend/modules/storage/_repository.py` — file metadata schema.
- `backend/modules/artefact/_repository.py` — artefact schema (note: `_id` is `ObjectId`, not UUID).
- `shared/dtos/project.py` — DTOs and `_Unset` sentinel pattern.
- `shared/topics.py:116` — existing project topics.
- `backend/modules/chat/__init__.py:44` — already-anticipates-`project_id` comment.

### Frontend

- `frontend/src/app/components/sidebar/Sidebar.tsx:120, 213, 369, 521, 705` — disabled-Projects markers and reserved slot.
- `frontend/src/app/components/sidebar/ZoneSection.tsx` — reusable zone container.
- `frontend/src/app/components/user-modal/UserModal.tsx` — modal shell to mirror.
- `frontend/src/app/components/user-modal/ProjectsTab.tsx` — stub to fill.
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — date-grouping, OPTION_STYLE pattern, candidate for `projectFilter` prop.
- `frontend/src/app/components/user-modal/UploadsTab.tsx`, `ArtefactsTab.tsx` — same.
- `frontend/src/app/layouts/AppLayout.tsx` — central NSFW filtering point.
- `frontend/src/features/chat/recentEmojisStore.ts` — LRU pattern to duplicate.
- `frontend/src/core/hooks/useViewport.ts` — `lg` breakpoint definition.
- `frontend/src/core/hooks/useChatSessions.ts` — Zustand+EventBus pattern to copy for `useProjects`.
- `frontend/src/core/websocket/eventBus.ts` — event subscription mechanism.

---

## 16. Implementation order — handoff to writing-plans

This spec is the input to `superpowers:writing-plans`. The plan will sequence the work so each step is independently testable. Expected coarse phases:

1. **Backend foundation:** data-model fields, indexes, public APIs, migration-free read-defaults, topics.
2. **Project-CRUD endpoints + safe-delete + full-purge.**
3. **Library merge in orchestrator** — verifiable via the test harness in `backend/llm_harness/`.
4. **Frontend: `useProjects` hook, `projectsApi.ts`, sidebar Projects-zone activation.**
5. **In-chat switcher + Project-Create-Modal.**
6. **`UserModal/ProjectsTab` activation + Project-Detail-Overlay (six tabs).**
7. **Persona overview default-project selector + project-detail-overlay personas tab actions.**
8. **NSFW filtering across all surfaces.**
9. **Delete modal + counts endpoint extension.**
10. **Mobile parity pass.**
11. **Manual verification §14.**
12. **Cleanup commit:** remove `PROJECTS-FEATURE.md` from repo root.
