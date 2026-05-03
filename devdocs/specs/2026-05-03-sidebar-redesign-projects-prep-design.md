# Sidebar Redesign & UX Cleanup (Projects Prep) — Design

**Date:** 2026-05-03
**Status:** Pending review
**Scope:** Frontend (sidebar, user-overlay tabs, chat top bar) + backend (persona `last_used_at`)

---

## Motivation

The desktop sidebar today is a single scroll container holding personas
(with a pinned/unpinned split), history (with a search input and `+N more`
overflow), and a busy bottom-nav of five data-viewer rows. As power users
accumulate personas and sessions, the result is the user's own description:
*chaos pur — und wir haben zuwenig platz für das, was notwendig sein wird*.

This spec ships an independent redesign **before** the upcoming Projects
feature, so that:

- Personas and History benefit from the calmer layout immediately.
- The Projects-zone slot is architected in but rendered invisibly until
  the Projects backend lands; flipping it on becomes a one-line change.
- Several long-standing UX bugs in adjacent surfaces (Personas-tab scroll,
  History-tab pin, in-chat pin) are fixed in the same pass while the
  surrounding code is touched.

The load-bearing UX promise is: *the user always sees, at a glance, items
from each of their three categories of pinned things*. The current sidebar
makes no such promise.

---

## Non-Goals

- **No mobile redesign in this spec.** The mobile drawer carries over
  unchanged. A follow-up session will mirror the relevant decisions to
  mobile after desktop is validated.
- **No Projects backend, data model, or UI.** Projects remain in
  `PROJECTS-FEATURE.md`. This spec only reserves the sidebar slot.
- **No new search-in-sidebar.** Search is modal-only going forward; the
  inline history search input is removed.
- **No drag-and-drop replacement mechanic.** Drag is removed; the order
  is implicit (LRU). No alternative manual-ordering UI is added.
- **No Bookmarks-feature changes.** Bookmarks gets a new sidebar position
  but the feature behaviour is untouched.
- **No accordion-mode toggle.** Free per-zone collapse only. If users
  later request mutually-exclusive collapsing, it can be added in one
  follow-up.

---

## Final Sidebar Structure (Desktop)

```
┌─────────────────────────────────────────────┐
│ 🦊 Chatsune                            ⏪   │  Header
├─────────────────────────────────────────────┤
│ 🪄 Admin                                    │  Admin (admin only)
├─────────────────────────────────────────────┤
│ 📝 New Chat ›                               │
│ 🕶️ New Incognito Chat ›                     │  Action block
│ ▶️ Continue ›  (only when applicable)        │
├─────────────────────────────────────────────┤
│ PERSONAS                          +     ∨   │
│   ▌ Aria         (pinned, gold-stripe)      │
│   ▌ Bran         (pinned, gold-stripe)      │  Entity
│     Dax          (LRU-fill)                 │  zones
│     Eddi         (LRU-fill)                 │
│     More… ›                                 │
│                                             │
│ [PROJECTS  zone — not rendered in v1]       │
│                                             │
│ HISTORY                                 ∨   │
│   ▌ "Q3 strategy"  (pinned, gold-stripe)   │
│     Recent chat about X  (LRU-fill)         │
│     More… ›                                 │
├─────────────────────────────────────────────┤
│ 🎓 Knowledge                                │
│ 🔖 Bookmarks                                │  Data block
│ 📂 My data ›                                │
├─────────────────────────────────────────────┤
│ 🔒 Sanitised                                │  Mode toggle
├─────────────────────────────────────────────┤
│ 👤 Chris                            ···     │  User block
│ ↪ Log out                                   │
└─────────────────────────────────────────────┘
```

### Top-to-bottom blocks

| Block | Rows | Notes |
|---|---|---|
| Header | Logo + collapse toggle | Unchanged |
| Admin | Admin banner | Admin/master-admin only, unchanged |
| Action | New Chat ›, New Incognito Chat ›, Continue › | Continue row only when `lastSession && !isInChat` |
| Entity zones | Personas, [Projects], History | Capped, collapsible — see §1 |
| Data | Knowledge, Bookmarks, My data › | Bookmarks moved here from bottom-nav; My data › replaces Uploads/Artefacts/Images |
| Mode | Sanitised toggle | Unchanged |
| User | Avatar+name+settings, Log out | Unchanged |

---

## §1 Entity Zones

The three entity zones are the structural heart of the redesign.
A **zone** is a collapsible section composed of a header row and a
content area whose height is dynamically allocated.

### 1.1 Allocation rule

Let `H` be the available vertical space inside the scrollable middle
container, after subtracting the action block above and the data block
below.

For each open zone: `max-height = (H − total_zone_headers_height) / open_zone_count`.

- 3 zones open → ~33% each.
- 2 zones open → ~50% each.
- 1 zone open → 100%.
- 0 zones open → only headers visible.

When v1 ships with Projects hidden, the formula naturally produces 50/50.
When Projects later joins, it becomes 33/33/33 with no extra logic.

Within its allocated max-height, each zone has `overflow-y: auto`. If
the zone contains more pinned + LRU-fill items than fit, it scrolls
internally — *the parent container does not grow*.

### 1.2 Zone header

```
PERSONAS                                  +    ∨
^                                         ^    ^
section label              add-action  collapse
```

- **Section label** (uppercase, dimmed, ~10px). Click anywhere on the
  header row (except `+`) toggles collapse.
- **`+` button** (only on Personas and Projects, not on History). Opens
  the entity's create flow. For Personas: same modal/route as today's
  "create persona" action. For Projects: deferred to Projects feature.
- **Collapse toggle** (`∨` open, `›` closed). Persists per zone in
  localStorage under `chatsune_sidebar_zone_<name>_open`.

### 1.3 Zone content

For each open zone the content stack is, in order:

1. **Pinned items** — sorted by LRU within the pinned subset, each with
   a left gold-stripe (see §2).
2. **Unpinned items** — sorted by LRU, rendered as plain rows.
3. **`More… ›`** — always the last row. Opens the user-overlay on the
   zone's full-management tab (Personas-tab, Projects-tab, History-tab).

All items are rendered; if the combined height exceeds the zone's
allocation (§1.1), the zone scrolls internally. There is no count-based
truncation. `More… ›` is *not* an overflow indicator — it is a
navigation shortcut to the entity's full management surface (search,
filter, delete, edit), which the sidebar deliberately does not provide.

Item rendering reuses the existing per-entity components (`PersonaItem`,
`HistoryItem`) but the wrapper drops drag-related props and adds the
gold-stripe class for pinned items.

### 1.4 Empty state

If a zone has zero pinned and zero unpinned items:

| Zone | Empty CTA | Click target |
|---|---|---|
| Personas | "No personas yet · Create one →" | Same as `+` |
| Projects | "No projects yet · Create one →" | Same as `+` (when feature lives) |
| History | "No conversations yet · Start a new chat →" | Same as Top "New Chat" row |

The History CTA is intentionally redundant with the top action row — for
new users this reinforces the path; once any chat exists this state is
never reached again.

### 1.5 Projects zone in v1

The Projects zone is **not rendered** in v1. It exists in the component
tree behind a feature gate (e.g. `PROJECTS_ENABLED = false` constant or
a config-driven flag, decided in the implementation plan). When the
Projects feature ships, flipping the gate on slots the zone in between
Personas and History; the allocation rule (§1.1) automatically rebalances.

No "Coming soon" placeholder. No disabled section. Invisible until live.

---

## §2 Pinned Indicator — Left Gold Stripe

Pinned items in any zone are marked with a 3-px-wide left border in
chatsune gold. The current pin indicators (background tint, star icon,
"Pinned" sub-headers) are removed.

### Visual specification

- `border-left: 3px solid rgba(212, 175, 55, 0.85)`
- `background: rgba(212, 175, 55, 0.03)` — a barely-perceptible warm
  tint that visually groups consecutive pinned rows.
- Padding compensates for the 3-px border so item text aligns with
  unpinned rows.

The stripe replaces both the today's *Pinned* sub-header and the per-row
star icon. It does not interact with selection/active state — an active
pinned item has the gold stripe **and** the active-state background.

### Where the stripe applies

Everywhere the pinned-state is rendered:

- Sidebar entity zones (this spec).
- Personas-tab in user-overlay (existing grid; pinned tile gets the
  stripe on its left edge).
- History-tab in user-overlay (existing list rows).
- Projects-tab when added.

Reference: `feedback_inline_marker_aesthetic` — small, present, non-intrusive.

---

## §3 LRU Replaces Manual Ordering

Drag-and-drop is removed everywhere it currently exists. Items are sorted
implicitly by **last used**, with pinned items grouped above unpinned
items, and LRU applied within each group.

### 3.1 Per-entity definition of "last used"

| Entity | "Last used" derived from |
|---|---|
| Persona | `personas.last_used_at` (new field, see §3.2) |
| Chat session | `chat_sessions.updated_at` (existing) |
| Project | Out of scope for this spec; defined in `PROJECTS-FEATURE.md` |

### 3.2 Backend change: `personas.last_used_at`

Add a new field to `PersonaDocument`:

```python
last_used_at: datetime | None = None
```

Backwards-compatible read: missing field → `None`. For sort purposes,
`None` falls back to the persona's `created_at` and sorts **descending**,
so a brand-new persona with no chat history appears at the top of the
unpinned list — the user sees it where they expect it.

The field is updated only when a chat session for the persona is
**created or resumed**, not on every message. The rationale: history
already tracks per-message activity through `chat_sessions.updated_at`;
re-bumping the persona on every message would couple a high-frequency
write path to the persona document for no UI benefit (the persona's
position in the sidebar does not need to refresh per message).

Hook points:

- Chat session creation (`backend/modules/chat/_repository.py:create_session`)
- Chat session resume — when an existing session is opened in a way
  that signals user intent (the exact event/handler is identified in
  the plan; navigating to `/chat/{persona}/{session}` is the likely
  trigger).

The bump is fire-and-forget — a failure to bump is logged and ignored,
not propagated to the chat write.

A WebSocket event is emitted: a `PERSONA_UPDATED` event with the new
`last_used_at` already covers it. No new topic needed.

### 3.3 What happens to `display_order`

The `display_order` field on `PersonaDocument` is no longer read by the
frontend. It remains in the document for backwards compatibility (per
beta-safety rules — no field removal without a migration). All write
paths that previously set it (drag-reorder endpoints) are unwired from
the frontend. The endpoints themselves (`PATCH /api/personas/reorder`)
remain functional but unused; deprecation/removal is a follow-up.

### 3.4 Removal of drag-and-drop

The following are removed:

- `@dnd-kit/core` and `@dnd-kit/sortable` imports from `Sidebar.tsx`
  and `PersonasTab.tsx`.
- `SortablePersonaItem`, `DraggableHistoryItem`, `DroppableZone`
  helpers in `Sidebar.tsx`.
- Persona reorder handler in `Sidebar.tsx` and `PersonasTab.tsx`.
- History session pin-by-drop handler in `Sidebar.tsx`.
- `__personasTabTestHelper` test seam in `PersonasTab.tsx`.

The `@dnd-kit/core`, `@dnd-kit/sortable`, and `@dnd-kit/utilities`
packages are removed from `package.json`. If a usage check during
implementation finds another consumer, that consumer is migrated as
part of this work; under no circumstances do `@dnd-kit/*` packages
ship in the post-redesign build.

---

## §4 Bottom Block: My data Consolidation

The five bottom-nav rows (Knowledge, Bookmarks, Uploads, Artefacts,
Images) are reorganised into:

```
🎓 Knowledge
🔖 Bookmarks
📂 My data ›
```

`Knowledge` and `Bookmarks` retain their current behaviour (open the
respective user-overlay tabs).

`My data ›` replaces the three separate rows for Uploads, Artefacts,
and Images. Click behaviour mirrors the existing mobile pattern: opens
the user-overlay on the **most recently visited** of the three sub-pages
(Uploads / Artefacts / Images), defaulting to Uploads on first visit.
The overlay's left navigation provides switching between them.

The "most recently visited" memory is per-user, persisted in
localStorage under `chatsune_my_data_last_subpage`.

The collapsed-rail variant of the desktop sidebar (50px-wide form)
similarly collapses the three icons into a single `📂 My data` icon
with the same click target.

---

## §5 Side Cleanups

Four orthogonal fixes/additions, included in this spec because the
surrounding code is touched.

### 5.1 Personas-tab scrollbar bug

**Bug:** `frontend/src/app/components/user-modal/PersonasTab.tsx` returns
a `<div className="flex flex-col gap-2 p-4">` with no `overflow-y`
declaration. Inside the user-modal's tab container, the persona list
overflows the viewport with no scroll handle.

**Fix:** Wrap the content in an `overflow-y: auto` container, matching
the pattern used by `HistoryTab` and other tabs.

### 5.2 Personas-tab "+" button

Add a "+ Create persona" button to the top-right corner of the
Personas-tab content area, parallel to the persona grid. Clicking opens
the same persona-creation flow used today by the `+ New persona` action
elsewhere.

### 5.3 History-tab per-row pin toggle

The History-tab list rows do not currently expose a pin toggle. Add a
pin/unpin icon to each row, visible:

- **Desktop:** on row hover.
- **Touch:** permanently visible (matches the existing convention
  elsewhere — touch devices show actions inline because there is no
  hover state).

Click toggles the session's `pinned` field via the existing
`onTogglePin` API; the WebSocket event is the existing
`CHAT_SESSION_PINNED_UPDATED`.

### 5.4 In-chat pin/unpin button

Add a pin/unpin icon to the chat top bar, adjacent to the chat title.
Click toggles `pinned` for the active chat session, calling the same
endpoint as the History-list pin action. The icon reflects current
state (filled = pinned, outline = not pinned).

**Location:** to the **right** of the chat title.

---

## §6 Feature-Gate Behaviour

The Projects-zone slot must be:

- Removed from the rendered tree (not just visually hidden) when the
  gate is off. This avoids any flash, hover artefact, or layout
  computation cost.
- Toggleable via a single constant or env-flag, so that flipping it on
  for the Projects feature is a one-line change.

Recommended gate: a `PROJECTS_ENABLED = false` constant in
`frontend/src/core/config/featureGates.ts` (new file, simple module
exporting boolean flags). The plan can revisit if a runtime flag is
preferable.

---

## §7 Migration & Beta Safety

Per CLAUDE.md (no more wipes after 2026-04-15), every change must be
backwards-compatible.

| Change | Migration strategy |
|---|---|
| `personas.last_used_at` (new field) | Default `None`. Reads use `doc.get("last_used_at") or doc.get("created_at")`. No script. |
| `personas.display_order` (deprecated) | Stays in document, no longer read by frontend. No removal. |
| `chatsune_sidebar_zone_<name>_open` (new localStorage keys) | Default to open if absent. Frontend-only. |
| `chatsune_my_data_last_subpage` (new localStorage key) | Default to "uploads" if absent. Frontend-only. |
| Removal of drag-related WebSocket reorder events | The endpoint stays operational; the frontend just stops calling it. No event-shape change. |

**No migration script needed.** All changes are additive on the read
path and removal-only on the write path (unused but functional
endpoints stay).

---

## §8 Manual Verification

A non-trivial UX change that touches several surfaces. Manual checks
on a real desktop browser, run by Chris before merge:

1. **Zone allocation.**
   - Collapse all three zones — only headers visible, scroll container
     not collapsed.
   - Open one zone — it gets the full free space.
   - Open two zones — they split 50/50.
   - Open three zones (only after Projects ships) — split 33/33/33.
   - Confirm each open zone scrolls internally when its content exceeds
     allocation.

2. **Pinned indicator.**
   - Pin and unpin a persona — gold stripe appears/disappears
     immediately, no page reload.
   - Pin and unpin a chat session in History zone — same.
   - Confirm active pinned item shows both the stripe and the active
     background.

3. **LRU and drag removal.**
   - Try to drag a persona in the sidebar — no movement, no haptic, no
     side effect.
   - Try to drag a persona on the Personas-tab in user-overlay — same.
   - Start a new chat with a persona that was at the bottom of LRU
     order — confirm it moves to the top of its group on next render
     (real-time via WebSocket, not just on reload).

4. **Action block.**
   - Continue row hidden when in chat.
   - Continue row hidden when no last session exists (e.g., new user).
   - Continue row visible and clickable when out of chat with prior
     sessions.

5. **My data ›.**
   - First click after install lands on Uploads sub-page.
   - Switch to Artefacts in overlay, close overlay, click `My data ›`
     again — lands on Artefacts.
   - Same for Images.

6. **Side cleanups.**
   - Personas-tab in user-overlay scrolls all the way to the bottom of
     a long persona list.
   - Personas-tab "+" button creates a new persona.
   - History-tab row shows pin icon on hover; click toggles pinned
     state and stripe in sidebar.
   - Chat top bar shows pin icon; click toggles pinned state and
     stripe in sidebar History zone.

7. **Empty states.**
   - Reset a test account to zero personas and zero chats — verify all
     three CTAs render and link correctly.

8. **Sanitised mode.**
   - Toggle sanitised mode — NSFW personas vanish from the Personas
     zone, NSFW sessions vanish from History zone, allocation
     rebalances correctly.

9. **localStorage persistence.**
   - Collapse Personas zone, reload — stays collapsed.
   - Same for History zone.

---

## §9 Reference: Files to Touch

Frontend (rough scope, definitive list deferred to plan):

- `frontend/src/app/components/sidebar/Sidebar.tsx` — major rewrite.
  Today this file is ~1170 lines and acts as a god-component. The
  rewrite **must** decompose it into focused sub-components: an
  action block, a zone (parameterised over entity type), a footer
  block, and the collapsed-rail variant. The exact split is part of
  the implementation plan.
- `frontend/src/app/components/sidebar/` — new `ZoneSection.tsx`
  component (or similar) for zone-allocation logic.
- `frontend/src/app/components/sidebar/PersonaItem.tsx` — drop drag
  props, add gold-stripe class for pinned.
- `frontend/src/app/components/sidebar/HistoryItem.tsx` — same.
- `frontend/src/app/components/sidebar/NavRow.tsx` — minor adjustments
  for the new bottom block.
- `frontend/src/app/components/user-modal/PersonasTab.tsx` — drag
  removal, scroll fix, add "+" button.
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — per-row
  pin toggle.
- `frontend/src/app/components/user-modal/UserModal.tsx` — wire up the
  "My data" entry point and last-subpage memory.
- `frontend/src/features/chat/ChatTopBar.tsx` (or whatever the actual
  chat header component is) — add pin/unpin icon.
- `frontend/src/core/store/sidebarStore.ts` — extend with per-zone
  collapse state.
- `frontend/src/core/config/featureGates.ts` — new file, exports
  `PROJECTS_ENABLED`.

Backend:

- `backend/modules/persona/_models.py` — add `last_used_at`.
- `backend/modules/persona/_repository.py` — bump on chat
  creation/continuation.
- `backend/modules/chat/_repository.py` (or `_handlers.py`) — call
  `persona_service.bump_last_used(...)` on chat events.
- `backend/modules/persona/__init__.py` — expose `bump_last_used`
  public API.

Shared:

- No changes to DTOs, events, or topics needed beyond the implicit
  inclusion of `last_used_at` in the existing `PersonaDto`.

---

## §10 Open Items for the Plan

The following remain implementation-detail decisions for the plan, not
the spec:

- **Exact identification of the "session resume" event/handler** that
  triggers the persona `last_used_at` bump (§3.2).
- **Concrete component decomposition of `Sidebar.tsx`** (§9) — the spec
  mandates the split; the plan picks the boundaries.
- **Concrete chat-header file path** for the pin-button addition (§5.4)
  — the plan locates the actual top-bar component.
