# Project Entity — Foundation (Step A)

**Date:** 2026-04-07
**Status:** Design approved, ready for implementation plan
**Scope:** Backend-only data foundation for the new `project` module. No frontend, no
integration with chats/artefacts, no sidebar. Goal is to have the entity, its contracts
and CRUD in place so we can subsequently reason about query patterns (e.g. fetching
artefacts by project) before building any UI.

---

## 1. Background & Intent

A *project* is a lightweight container that will eventually group chats and carry
project-scoped knowledge. The mental model is closer to ChatGPT's projects than to
Claude's: a folder "on steroids" — easy to grasp for non-professional users, but with
room for organised knowledge later.

Step A creates only the entity itself. Everything that connects projects to other
modules (chats, artefacts, knowledge libraries, sidebar, pinning UI, NSFW propagation
into sanitised mode) is explicitly out of scope and will follow in later steps.

This is the most data-intensive feature on the roadmap, which is why it is broken
into deliberate, small steps.

---

## 2. Module Layout

A new module `backend/modules/project/`, structured analogously to `persona` and
`knowledge`:

```
backend/modules/project/
  __init__.py        # exports ProjectService (sole public API)
  _models.py         # ProjectDocument (internal MongoDB shape)
  _repository.py     # ProjectRepository, encapsulates the collection
  _handlers.py       # FastAPI routes, calls ProjectService
```

The only symbol exported from `__init__.py` is `ProjectService`, with the methods
`list_for_user`, `get`, `create`, `update`, `delete`. All future cross-module access
goes through this service — no other module ever touches the `projects` collection
directly.

---

## 3. Data Model

MongoDB collection: `projects`. Document shape:

```python
class ProjectDocument(BaseModel):
    id: str                    # UUID, stored as _id
    user_id: str               # owner, mandatory
    title: str                 # 1–80 chars after strip(), non-empty
    emoji: str | None          # exactly one grapheme, or None
    description: str           # 0–2000 chars, default ""
    nsfw: bool                 # default False
    pinned: bool               # default False — NOT writable in step A
    sort_order: int            # default 0     — NOT writable in step A
    created_at: datetime
    updated_at: datetime
```

**Deliberately omitted:** `knowledge_library_ids`. The cross-module relationship to
the `knowledge` module needs its own design pass before the field even exists.

### Indexes

- `{ user_id: 1, created_at: -1 }` — default per-user listing, newest first
- `{ user_id: 1, pinned: -1, sort_order: 1, created_at: -1 }` — prepared for the
  later sidebar ordering. Costs nothing now, saves a migration later.

### Validation rules (Pydantic validators)

- `title`: `title.strip()` must be non-empty; the stripped value's length must be
  between 1 and 80 inclusive.
- `emoji`: when not `None`, `grapheme.length(emoji)` must equal 1. Uses the
  `grapheme` library.
- `description`: maximum 2000 characters. No strip requirement.

---

## 4. Shared Contracts

### `shared/dtos/project.py`

```python
class ProjectDto(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    description: str
    nsfw: bool
    pinned: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

class ProjectCreateDto(BaseModel):
    title: str
    emoji: str | None = None
    description: str = ""
    nsfw: bool = False

class ProjectUpdateDto(BaseModel):
    # All fields optional → partial update
    title: str | None = None
    emoji: str | None = Field(default=UNSET)   # sentinel; see below
    description: str | None = None
    nsfw: bool | None = None
```

**PATCH semantics for `emoji`:** because plain `None` would be ambiguous between
"don't touch" and "clear the field", `emoji` uses an explicit `UNSET` sentinel as
its default. The handler distinguishes:

- field absent / `UNSET` → leave the existing value alone
- field present and `None` → clear the emoji
- field present and a string → set the new emoji (after grapheme validation)

### `shared/events/project.py`

```python
class ProjectCreatedEvent(BaseModel):
    project: ProjectDto

class ProjectUpdatedEvent(BaseModel):
    project: ProjectDto

class ProjectDeletedEvent(BaseModel):
    project_id: str
```

### `shared/topics.py`

Three new constants:

```python
PROJECT_CREATED = "project.created"
PROJECT_UPDATED = "project.updated"
PROJECT_DELETED = "project.deleted"
```

### Event scope

All three events are published with scope `user:<user_id>` so that every active
session of the same user receives them.

---

## 5. REST Endpoints

All endpoints sit under `/api/projects`, all require authentication, all filter by
the `user_id` taken from the access token.

| Method | Path                  | Body                | Response                                 | Event              |
|--------|-----------------------|---------------------|------------------------------------------|--------------------|
| GET    | `/api/projects`       | —                   | `list[ProjectDto]`, sorted `created_at desc` | —                |
| GET    | `/api/projects/{id}`  | —                   | `ProjectDto` or 404                      | —                  |
| POST   | `/api/projects`       | `ProjectCreateDto`  | `ProjectDto` (201)                       | `PROJECT_CREATED`  |
| PATCH  | `/api/projects/{id}`  | `ProjectUpdateDto`  | `ProjectDto`                             | `PROJECT_UPDATED`  |
| DELETE | `/api/projects/{id}`  | —                   | 204                                      | `PROJECT_DELETED`  |

### Behaviour

- Accessing a project owned by a different user returns **404**, not 403, so we do
  not leak existence.
- Validation errors return 422 with the standard Pydantic detail body.
- Events are published **after** the database write succeeds, each with its own
  `correlation_id` derived from the request.
- The list endpoint sorts by `created_at desc` for now. Pinning and `sort_order`
  will be honoured once the sidebar consumes them in step B.

---

## 6. Tests

Pytest, against a real MongoDB instance, consistent with the rest of the repository.

**Repository layer**
- create → get round-trip
- partial update preserves untouched fields
- delete removes the document
- user isolation: user A cannot see, update or delete user B's project

**Validation**
- empty / whitespace-only title → rejected
- title exceeding 80 characters → rejected
- multi-grapheme emoji → rejected
- description exceeding 2000 characters → rejected

**Handler layer**
- 401 without a valid token
- 404 when accessing another user's project (existence not leaked)
- 422 on malformed bodies
- emoji PATCH sentinel semantics: absent → unchanged, explicit `null` → cleared,
  string → updated

**Event publishing**
- each successful mutation publishes exactly one event
- the event uses the correct topic and carries the up-to-date DTO
- events are scoped to `user:<user_id>`

---

## 7. Error Handling

Standard FastAPI exceptions only. This module does **not** emit `ErrorEvent` — those
are reserved for asynchronous operations where the client cannot observe the failure
through an HTTP response. CRUD failures are synchronous and visible via status codes.

---

## 8. Out of Scope (Step A)

The following items are explicitly **not** part of this step. They exist in the
roadmap but belong to later steps and must not be implemented now:

- Any frontend code (no `frontend/src/features/project/`)
- Sidebar integration, user-overlay project list, dedicated project view page
- Making `pinned` or `sort_order` writable through the CRUD surface
- The `knowledge_library_ids` field and the merge-with-persona-libraries logic
- Linking projects to chats or artefacts (no `project_id` foreign key anywhere yet)
- Cascade behaviour on delete ("poof, the container is gone, the contents fall on
  the floor"). Step A only deletes the project document itself; the cascade lives in
  whichever modules later add a `project_id` field.

---

## 9. Decision Log

- **Schema breadth:** middle road. Include `pinned` and `sort_order` in the document
  from day one (no migration later), but exclude `knowledge_library_ids` until the
  cross-module relationship is properly designed.
- **Ownership:** strictly per-user. No sharing, no `visibility` placeholder. Sharing
  is YAGNI for a privacy-first self-hosted tool.
- **Lifecycle:** hard delete with future cascade. The project document is removed
  immediately; chats and artefacts will, once they have a `project_id`, fall back to
  "loose" rather than be deleted with the project.
- **Validation:** pragmatic-strict. Title 1–80, description 0–2000, single grapheme
  emoji, no per-user project limit.
- **Events:** minimal CRUD trio. One `updated` event carrying the full DTO instead
  of granular per-field events. No initial-snapshot event — that becomes a normal
  REST `GET` when the overlay is built.
- **Transport:** REST mutations + event confirmation, consistent with the other
  modules in the codebase.
- **Update surface:** strictly the four base fields. `pinned` and `sort_order` stay
  read-only until the sidebar work needs them and can test them.
