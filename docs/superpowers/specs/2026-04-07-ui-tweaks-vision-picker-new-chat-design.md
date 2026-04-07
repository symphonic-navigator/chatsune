# UI Tweaks: Vision Fallback Picker & New Chat Button

Date: 2026-04-07
Status: Approved

Two small UI improvements bundled into one spec:

1. Replace the leaky vision-fallback `<select>` in the persona editor with the
   shared `ModelSelectionModal`, restricted to vision-capable models.
2. Add a "New Chat" entry point to the main sidebar that expands an inline
   persona picker.

A third reported point — disabling reasoning during vision-fallback
description — is already implemented at
`backend/modules/chat/_vision_fallback.py:100` (`reasoning_enabled=False`).
No change required; mentioned here for traceability.

---

## 1. Vision Fallback Picker

### Current state

`frontend/src/app/components/persona-overlay/EditTab.tsx:417` renders a native
`<select>` populated by flattening enriched models from every provider and
filtering by `supports_vision`. Each option label is built as
`<provider_id> – <display_name>` (e.g. `ollama_cloud – qwen2.5vl`), which
exposes the provider id to the user — a leaky abstraction that will get worse
as more providers are added.

### Goal

Reuse the existing shared model picker (`ModelSelectionModal` /
`ModelBrowser`), but constrain it so only vision-capable models can be
chosen and shown. The user must not be able to disable that constraint.

### Design

**Reusable mechanism — `lockedFilters` prop.** Add an optional
`lockedFilters` prop to `ModelSelectionModal` and `ModelBrowser`:

```ts
interface LockedFilters {
  capVision?: true
  capTools?: true
  capReason?: true
}
```

Behaviour when a filter is locked:

- The corresponding entry in the internal `filters` state is forced to
  `true` and cannot be toggled off.
- The matching capability toggle button in `ModelBrowser` renders in an
  active-but-disabled style (active styling, `disabled` attribute,
  `cursor-not-allowed`, tooltip "Required for this selection").
- `filterModels` already honours these flags, so no filter logic changes
  are needed beyond ensuring the locked flag is always set.

This is a generic mechanism so other "constrained pickers" (e.g. a
future tool-only picker) can use it without further changes.

**EditTab integration.** Replace the native `<select>` block with:

- A trigger button styled like the existing "Change model" button used for
  the primary chat model. It shows the currently selected vision fallback
  model's `display_name`, or "No fallback" if `null`.
- Next to it, a small "Clear" button (only visible when a fallback is set)
  that sets `visionFallbackModel` back to `null`.
- Clicking the trigger opens `ModelSelectionModal` with
  `lockedFilters={{ capVision: true }}` and `currentModelId={visionFallbackModel}`.
- On select, store `model.unique_id` into `visionFallbackModel` state.

The existing `useEffect` that loaded `visionCapableModels` across providers
and the related state can be deleted. The picker handles its own loading
via `useEnrichedModels`.

### Files touched

- `frontend/src/app/components/model-browser/ModelBrowser.tsx` — add
  `lockedFilters` prop, force flags, render locked toggles disabled.
- `frontend/src/app/components/model-browser/ModelSelectionModal.tsx` —
  add `lockedFilters` prop, pass through to `ModelBrowser`.
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — remove
  native `<select>` + `visionCapableModels` state/effect; render trigger
  button + clear button + modal.

### Out of scope

- No changes to `filterModels` logic (already correct).
- No changes to the backend.

---

## 2. New Chat Button in Sidebar

### Current state

To start a new chat, users must navigate to the personas page or pick a
persona from the sidebar persona list. Multiple users have asked for a
faster path. The persona list in the sidebar is also pinned-personas-only
by default; unpinned personas live behind an "Other Personas" expander.

### Goal

A single, prominent "New Chat" affordance that lets the user pick **any**
persona (pinned or not) and immediately starts a new chat with it.

### Design

**Placement.** A new sidebar row inserted into `Sidebar.tsx` immediately
above the "Personas" section header (currently around `Sidebar.tsx:424`).
For admins, this row appears below the existing ADMIN section so the
overall order is: ADMIN → New Chat → Personas → … . For non-admins:
New Chat → Personas → … .

**Trigger.** A `NavRow`-style button:

- Icon: 🪶 (quill)
- Label: "New Chat"
- Click toggles an inline expanded panel directly underneath, in the same
  visual idiom as the existing "Other Personas" expander.

**Expanded panel content.** A flat sorted list of personas, identical to
how `PersonasTab.tsx` (user modal) sorts them:

```ts
const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
const sorted = sortPersonas(filtered)
```

- **Sanitised mode is honoured** — the same `useSanitisedMode` hook used
  elsewhere filters NSFW personas out when sanitised mode is on.
- Sorting uses the existing `sortPersonas` helper from the user modal so
  ordering matches the personas overview page exactly.
- Each entry: small avatar/colour dot + persona name. Hover highlight.
  No search field, no group headers, no NSFW indicator inside this list
  (the indicator only matters where the persona is browsed; here the user
  is committing to a chat).

**Click behaviour.** Clicking a persona entry:

1. Calls the existing "create new chat session for persona" flow (the same
   one used by the personas overview page; identify the exact action when
   writing the implementation plan).
2. Navigates to the new chat.
3. Collapses the panel.

**Collapse behaviour.** The panel collapses when:

- A persona is selected (above), OR
- The user clicks the "New Chat" trigger again, OR
- The user clicks anywhere outside the panel inside the sidebar body.

The collapse state is local component state — not persisted across
sessions.

**Empty state.** If `sorted.length === 0` (e.g. no personas yet, or all
hidden by sanitised mode), show a subdued "No personas available" line
inside the expanded panel.

### Files touched

- `frontend/src/app/components/sidebar/Sidebar.tsx` — insert new row +
  expanded panel above the Personas section.
- Possibly extract `sortPersonas` from `user-modal/` into a shared helper
  if it isn't already importable from outside that folder. Decide while
  writing the plan; do not duplicate the function.

### Out of scope

- No changes to persona data, NSFW flagging, or sanitised mode logic.
- No changes to the personas overview page.
- No keyboard navigation inside the expanded panel beyond what comes for
  free from native button focus.

---

## Testing

- **Vision picker:** Vitest unit test for `ModelBrowser` verifying that
  with `lockedFilters={{ capVision: true }}` the vision toggle is rendered
  active+disabled and the filtered list contains only vision-capable
  models. Existing EditTab tests (if any) updated to use the new picker
  trigger.
- **New chat button:** Vitest test for `Sidebar.tsx` verifying:
  - Row renders above "Personas" and (when admin) below ADMIN.
  - Click expands the panel, second click collapses.
  - Sanitised mode hides NSFW personas from the panel list.
  - Clicking a persona triggers the new-chat action and navigation.

## Build verification

After implementation: `pnpm run build` (or `pnpm tsc --noEmit`) must pass
cleanly. Backend untouched.
