# Artefacts Page — Design

**Date:** 2026-04-07
**Status:** Draft, awaiting review

## Goal

Give users a global view of every artefact they have produced across all chat
sessions, with filtering, search, rename, delete, and a "jump to chat"
shortcut that opens the artefact in the originating session.

The page must respect persona incognito mode: artefacts whose owning persona
is currently incognito are hidden completely (plausible deniability — they do
not appear in the list, in the count, in search results, or in filter
dropdowns).

## Non-goals

- No in-page editor or preview overlay (we deliberately avoid duplicating the
  existing `ArtefactOverlay`, which is tightly coupled to the chat session
  context). Editing happens in the chat via the existing overlay after the
  user jumps there.
- No bulk operations (multi-select delete, etc.) in this iteration.
- No new artefact types or storage changes.

## Backend

### New endpoint

`GET /api/artefacts/`

Lives in the `chat` module (artefacts already belong to it). Returns all
artefacts owned by the authenticated user across all sessions, sorted by
`updated_at desc`.

### New DTO

`ArtefactListItemDto` in `shared/dtos/chat.py` (or a new
`shared/dtos/artefact.py` if cleaner — to be decided during planning):

```python
class ArtefactListItemDto(BaseModel):
    id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None
    size_bytes: int
    version: int
    created_at: datetime
    updated_at: datetime
    session_id: str
    session_title: str
    persona_id: str
    persona_name: str
    persona_accent: str  # for monogram colour
```

### Implementation

`ChatService` (or its artefact submodule) gains `list_user_artefacts(user_id)`.
The repository performs a single MongoDB aggregation that joins artefacts with
their session documents to obtain `session_title` and `persona_id`. Persona
name and accent are then resolved via `PersonaService.get_persona(...)` —
**never** by querying the personas collection directly (module boundary).

For the typical user with a few hundred artefacts the per-persona resolve is
acceptable. If needed later, persona data can be batched.

Existing endpoints `PATCH` and `DELETE` are reused for rename and delete; no
new write endpoints are added.

## Frontend

### Route and entry point

- New page: `frontend/src/app/pages/ArtefactsPage.tsx`
- Wired into the existing sidebar navigation alongside History, Knowledge,
  Personas, etc.

### Data layer

- `frontend/src/core/api/artefact.ts` gains `listAll()` calling
  `GET /api/artefacts/`.
- `frontend/src/core/types/artefact.ts` gains `ArtefactListItem` matching the
  backend DTO.
- A small page-local hook `useArtefactsList()` fetches once on mount and
  subscribes to artefact lifecycle events
  (`artefact.created`, `artefact.updated`, `artefact.deleted`) so the list
  stays in sync without polling.

### Layout

```
┌─ Toolbar ────────────────────────────────────────────────────┐
│ [Persona ▼]  [Type ▼]  [search...]                n results  │
├──────────────────────────────────────────────────────────────┤
│ ◉ CL  Snake Game                  code     Game ideas        │
│       2026-04-05 14:32                              ⋯        │
│ ◉ MR  Recipe                      markdown Dinner planning   │
│       2026-04-04 09:11                              ⋯        │
└──────────────────────────────────────────────────────────────┘
```

Columns per row: persona monogram (in persona accent colour), title, type
badge, session title, timestamp, action menu.

### Filters and search (all client-side)

- **Persona filter:** dropdown listing "All personas" + every persona that
  owns at least one *visible* artefact. Personas in incognito mode are not
  included.
- **Type filter:** "All types" + the six `ArtefactType` values.
- **Search:** case-insensitive contains over `title`. Whitespace-separated
  tokens are combined with **AND** (every token must appear somewhere in the
  title).
- All filters and search compose. The result count reflects the filtered set.

### Sanitised mode (incognito)

Artefacts whose persona has `incognito === true` (read from `personaStore`)
are removed from the working set **before** any filter, search, or count
runs. They are invisible to the page in every respect. When a persona is
toggled incognito on/off via its existing event, the list re-derives
automatically because the store change triggers a re-render.

### Rename (inline)

Double-click the title in a row replaces it with an input pre-filled with
the current title.

- Enter → call `artefactApi.patch(sessionId, id, { title })`, optimistically
  update the local list.
- Esc or blur without change → cancel.
- Empty title → reject and keep edit mode.

### Delete

Action menu → "Delete" → existing confirm pattern (toast or small modal,
matching what `ChatSessionList` uses for session delete). On success, remove
from local list. The existing `artefact.deleted` event will arrive too and
be a no-op.

### Open in chat

Action menu → "Open in chat" (also the default click on the row body).

1. `useNavigate('/chat/' + sessionId, { state: { pendingArtefactId: id } })`.
2. `ChatPage` reads `location.state.pendingArtefactId` once on mount /
   when session data is ready, calls `artefactStore.openOverlay(id)`, then
   clears the state via `history.replaceState` so a reload does not re-open
   the overlay.

This satisfies the user's wish to also see the surrounding conversation that
produced the artefact.

## Events

Per project rule (Event-First, no exceptions): every state change must be
visible to the user via an event. For this feature:

- **Rename** uses the existing `PATCH /api/chat/sessions/{sid}/artefacts/{id}`
  which already publishes `Topics.ARTEFACT_UPDATED` with an
  `ArtefactUpdatedEvent`. Verify the event payload contains the fields the
  Artefacts page needs (`title`, `updated_at`); if not, extend the existing
  event DTO in `shared/events/` rather than adding a new event.
- **Delete** uses the existing `DELETE` endpoint which already publishes
  `Topics.ARTEFACT_DELETED`. The list page subscribes and removes the row.
- **Create** (artefacts produced inside a chat) already emits
  `Topics.ARTEFACT_CREATED`. The list page subscribes and inserts new rows
  at the top so a freshly produced artefact appears immediately even if the
  user was already on the Artefacts page.
- **Persona incognito toggle** already emits an event consumed by
  `personaStore`; no new event needed — the page re-derives from the store.
- **No new endpoints introduce silent state changes.** The new
  `GET /api/artefacts/` is read-only. If during planning we discover any
  write path that lacks an event, we add the event to `shared/events/` and
  the topic to `shared/topics.py` *first*, then wire it up.

Verification step during planning: enumerate every artefact-related event
already defined in `shared/events/` and `shared/topics.py`, confirm each
covers the fields the page needs, and only extend (never duplicate).

## Error handling

- List fetch failure: standard error toast plus a retry affordance in the
  empty state.
- Rename failure: revert optimistic update, show error toast.
- Delete failure: revert removal, show error toast.
- Navigation to a session that no longer exists (race): ChatPage already
  handles 404; the artefact open will simply no-op.

## Testing

- Backend: a unit test for `list_user_artefacts` covering the join and the
  PersonaService integration. An API test verifying ownership scoping (a
  user cannot see another user's artefacts).
- Frontend: a Vitest test for the filter/search reducer (incognito hiding,
  AND token search, persona/type filter composition).
- No tests for trivial rendering.

## Open items

None. Ready for review.
