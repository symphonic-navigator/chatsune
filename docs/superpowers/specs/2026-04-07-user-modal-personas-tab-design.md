# UserModal Personas Tab + Overview Model Display

**Date:** 2026-04-07
**Status:** Approved

## Motivation

Two independent users have flagged that the "flow" through the UserModal feels
incomplete: there is no convenient way to see, pin, and reorder personas from
within the modal. A separate observation: the persona overview page does not
show which model the persona is bound to, even though "model = capabilities"
is one of the most important pieces of information about a persona — not just
hard caps but also "how the model behaves".

## Scope

1. New `personas` tab in `UserModal`, between `about-me` and `projects`.
2. Compact, sortable, pin-able persona list inside that tab, fully wired to
   the existing event system.
3. Model identifier displayed on `persona-overlay/OverviewTab.tsx`, styled
   identically to how `PersonaCard` already shows it.

Out of scope:

- New events, DTOs, or backend routes — everything required already exists.
- Capability badges (vision/tools/reasoning) — bewusst minimal, matching the card.
- Bulk actions, filters, search, persona creation from the tab.

## Architecture

### New tab registration

`frontend/src/app/components/user-modal/UserModal.tsx`

- Add `'personas'` to the `UserModalTab` union, between `'about-me'` and
  `'projects'`.
- Add a `Tab` entry in the `TABS` array in the same position.
- Render `<PersonasTab onClose={onClose} />` when active.

### New file: `PersonasTab.tsx`

`frontend/src/app/components/user-modal/PersonasTab.tsx`

Reuses the **existing** personas state and event subscriptions used by
`PersonasPage` and `Sidebar` — no new fetching, no new event handlers.
Whatever store/hook (`usePersonasStore` or equivalent) those screens consume
is the single source of truth here too. Live updates flow in automatically
via `persona.created`, `persona.updated`, `persona.deleted`,
`persona.reordered`.

Sorting: pinned first, then `display_order` ascending — identical to
`PersonasPage`.

**Sanitised mode filtering:** before rendering, filter out personas where
`nsfw === true` using the existing sanitised-mode selector. The personas
must not appear at all (plausible deniability — no visual hint they exist).

### Row layout

A vertically stacked list using `@dnd-kit/sortable` with
`verticalListSortingStrategy`. Each row:

```
[≡] [MO] [avatar]  Display Name                  [💋?] [📌]
                   tagline (one line, truncated)
                   model-slug (mono, chakra hex + "4d")
```

- **Drag handle** (`≡`): uses `useSortable` listeners. Pattern follows
  `frontend/src/app/components/sidebar/PersonaItem.tsx`.
- **Monogram + avatar:** small variant (~32px), chakra-tinted matching the
  card's treatment.
- **Display name:** primary text.
- **Tagline:** second line, muted, truncated with ellipsis.
- **Model:** third mini-line, monospace, colour `chakra.hex + "4d"`,
  text = `persona.model_unique_id.split(":").slice(1).join(":")`.
  Exact reproduction of `PersonaCard.tsx:226–230`.
- **NSFW indicator (💋):** rendered only in non-sanitised mode (in sanitised
  mode the persona itself is filtered out, so this code path never runs for
  NSFW personas there). Position: just before the pin toggle.
- **Pin toggle (📌):** behaviour and styling match `PersonaCard.tsx:135` —
  chakra hex when active, muted otherwise. Click toggles `pinned` via the
  existing persona update route.

### Interactions

- **Row click** (anywhere except the drag handle, the NSFW icon, and the pin
  toggle): closes the UserModal via `onClose()` and opens the persona overlay
  on the `overview` tab using the existing
  `openPersonaOverlay(personaId, "overview")` bridge. Pattern follows
  `BookmarksTab` / `HistoryTab`, both of which already accept `onClose` and
  delegate navigation that way.
- **Drag end:** call the existing `PATCH /personas/reorder` route with the
  new `ordered_ids`. The resulting `persona.reordered` event then refreshes
  every other consumer automatically — no local mutation needed beyond
  optimistic reordering during the drag.
- **Pin toggle:** call the existing persona update route with
  `pinned: !current`. Live event updates handle the rest.

### OverviewTab extension

`frontend/src/app/components/persona-overlay/OverviewTab.tsx`

Add a model line directly below the tagline:

- Monospace font.
- Colour `chakra.hex + "4d"` (gedämpft, identisch zu `PersonaCard`).
- Text: `persona.model_unique_id.split(":").slice(1).join(":")`.
- No icons, no provider pill, no capability badges.

## Event-system wiring summary

| User action               | Existing route / event used                      |
|---------------------------|--------------------------------------------------|
| Open tab                  | Reuses cached persona state populated by events  |
| Reorder via drag          | `PATCH /personas/reorder` → `persona.reordered`  |
| Pin / unpin               | Persona update route → `persona.updated`         |
| Open overview             | Frontend-only navigation (`openPersonaOverlay`)  |
| Sanitised mode toggle     | Existing sanitised-mode selector re-filters list |

Nothing new in `shared/`. Nothing new in `backend/modules/persona/`.

## Testing

- Frontend smoke test for `PersonasTab` rendering with mocked persona state:
  - Sorting (pinned first, then `display_order`).
  - NSFW personas filtered in sanitised mode.
  - Pin toggle invokes update.
  - Reorder invokes `bulk_reorder`.
- Light test for `OverviewTab` rendering the new model line.
- Existing `UserModal.test.tsx` updated to know about the new tab id.

## Build verification

After implementation:

- `pnpm tsc --noEmit`
- `pnpm run build`
- `pnpm test` for the affected component tests.

## Files touched

Created:

- `frontend/src/app/components/user-modal/PersonasTab.tsx`
- `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`

Modified:

- `frontend/src/app/components/user-modal/UserModal.tsx` — register new tab
- `frontend/src/app/components/persona-overlay/OverviewTab.tsx` — model line
- `frontend/src/app/components/user-modal/UserModal.test.tsx` — tab id
