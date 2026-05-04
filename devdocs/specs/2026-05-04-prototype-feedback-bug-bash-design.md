# Prototype Feedback Bug Bash — Design

**Date:** 2026-05-04
**Source:** Discord-collected user feedback from prototype testers, plus
one external iPhone-PWA report.

This bundles seven small, mostly-independent fixes and improvements into a
single round. None of them is large enough to deserve its own spec, but
they do span sidebar, persona-overlay, persona-card, LLM-provider config,
and global mobile-PWA layout — so we capture the intent here, then plan
and execute as one batch.

---

## Goals

- Fix two reported bugs (items 1 and 7).
- Adjust three UI pain-points reported by multiple testers (items 2, 3, 5).
- Address one consistent friction in API-key entry (item 4).
- Best-effort fix for two iPhone-PWA-only issues (items 6, 7) — verified
  by the reporting tester after deployment, since we have no iPhone in
  the dev loop.

## Non-Goals

- No backend / data-model changes. The chat-session-rename API
  needed for Item 5 already exists on both backend and frontend; all
  seven items are frontend-only.
- No global theming, design-system, or accessibility-pass overhaul.
  Each item is targeted and small.

---

## Items

### Item 1 — User-modal "+ Create persona" lands on overview, not edit

**Reported behaviour:** In the user-modal Personas tab, the "+ Create
persona" button takes the user to a "persona overview" instead of
opening the new-persona creation form.

**Current code:**

- `frontend/src/app/components/user-modal/PersonasTab.tsx` renders the
  button and wires `onClick={onCreatePersona}`.
- `frontend/src/app/layouts/AppLayout.tsx:334` provides the handler:
  `onCreatePersona={() => openPersonaOverlay(null, "edit")}`.
- `openPersonaOverlay(null, "edit")` sets state
  `{ personaId: null, tab: "edit" }`.
- `<PersonaOverlay isCreating={personaOverlay.personaId === null}
  activeTab={personaOverlay.tab} ... />` is rendered with
  `isCreating={true}`, `activeTab="edit"`.
- `PersonaOverlay.tsx:298` guards the OverviewTab render with
  `activeTab === 'overview' && !isCreating`, so it should not show.

On paper this should already open the EditTab. We don't yet have a
confirmed reproduction path that isolates the actual bug. Two
hypotheses:

1. The user is reading "I see the personas grid page" as "overview" —
   meaning the user-modal closes but the persona-overlay never mounts
   (e.g. a race between modal-close and overlay-open).
2. The overlay does mount but the EditTab is rendering an empty,
   read-only-feeling state that the user reads as "overview".

**Plan:** During implementation, reproduce locally first. Likely
candidates to check, in order:

1. Verify that clicking "+ Create persona" in the user-modal actually
   results in the persona-overlay being mounted (devtools React tree).
2. If the overlay mounts but the EditTab shows nothing actionable,
   inspect EditTab for a `persona` truthiness guard that shortcuts
   when `persona === null` even though `isCreating === true`.
3. If the overlay never mounts, inspect the modal close path —
   `setModalOpen(false)` and `setPersonaOverlay({ ... })` are both
   called from `openPersonaOverlay`, so the order is fine, but a
   secondary effect inside the user-modal might be re-opening the
   personas grid behind it.

**Expected fix shape:** A small adjustment in either the EditTab
empty-state rendering or the overlay mount sequence. No API change.

**Acceptance:** From any tab in the user-modal, clicking "+ Create
persona" closes the user-modal and shows the persona-overlay with the
Edit tab active, ready to accept name/colour/etc.

---

### Item 2 — Add "Import from file" button next to "+ Create persona" in PersonasTab

**Current state:** PersonasTab top bar has only the "+ Create persona"
button. Import is currently only reachable from the personas grid page
(via the AddPersonaCard's popover menu), so users who are already in the
user-modal have no path.

**Change:**

- Add a second button left of "+ Create persona", labelled
  "⤓ Import" (or similar — match the existing menu's "Import from
  file" wording for consistency).
- Use the same wiring as the personas grid: a hidden `<input
  type="file">` plus the existing `personasApi.importPersona` flow.
- On success, close the user-modal and navigate the user into the
  freshly-imported persona's overview, exactly like the grid path
  does today.
- Style: match the existing "+ Create persona" button — same border,
  padding, type-size, hover.

**Acceptance:** Same import flow as the personas-grid card, but
reachable from inside the user-modal.

**Implementation note:** The import logic in `PersonasPage.tsx`
(`handleImportClick`, `handleFileSelected`, the importing-overlay JSX)
is not currently shared. A small extraction — either a local hook or a
shared component for "the file-input + spinner pair" — is in scope if
it makes the duplication painless. Not required if it's cleaner to
inline.

---

### Item 3 — Replace AddPersonaCard menu with a vertical split

**Current state:** On the personas grid, the AddPersonaCard is a single
big "+" card that, on click, opens a small popover menu
(`AddPersonaMenu`) with two options: "Create new" and "Import from
file". Testers find the menu fiddly and it has caused minor layout
issues.

**Change:**

- The card stays the same outer size (height/width unchanged from
  current `clamp(160px, 42vw, 210px) × clamp(240px, 63vw, 320px)`).
- Internally split it vertically into two equal halves with a subtle
  divider between them.
- Top half: Plus icon + "Add persona" label — clicking it triggers the
  same path as today's "Create new" menu item.
- Bottom half: Down-arrow / file icon + "Import from file" label —
  clicking it triggers the same path as today's "Import" menu item.
- Both halves are buttons in their own right, with hover affordances.
- Delete `AddPersonaMenu.tsx` entirely.
- Remove the popover state (`menuOpen`, the wrapping `<div
  className="relative">`, the menu render) from `PersonasPage.tsx`.

**Layout details:**

- Each half is itself a `flex flex-col items-center justify-center`
  with a small icon and a font-mono uppercase label, mirroring the
  existing card aesthetic.
- The divider is a single 1px horizontal line in
  `rgba(201,168,76,0.15)` to match the dashed border colour.
- Hover only highlights the half being hovered, not the whole card.
- The card-entrance animation stays as today (one animation on the
  outer card).

**Accessibility:**

- Each half is a `<button>` with an `aria-label` ("Create new persona"
  / "Import persona from file").

**Acceptance:** No menu pop-up. Two clear click targets stacked
vertically inside the card. Both flows still work end-to-end.

---

### Item 4 — Suppress browser password-manager prompts on API-key fields

**Current state:** API-key inputs in
`frontend/src/app/components/llm-providers/adapter-views/` and
`CommunityView.tsx`, `OllamaHttpView.tsx`, `XaiHttpView.tsx` all use
`type="password"` plus `autoComplete="new-password"`. Browsers ignore
the autocomplete hint for password-typed inputs and still offer to
save the value as a password — confusing for users entering an API
key.

**Change:** Convert each affected input from `type="password"` to
`type="text"` and mask its value visually via CSS:

```tsx
style={{ WebkitTextSecurity: 'disc' } as React.CSSProperties}
```

Also add password-manager-bypass attributes:

```tsx
autoComplete="off"
data-1p-ignore
data-lpignore="true"
data-bwignore="true"
```

The cast to `React.CSSProperties` is needed because
`-webkit-text-security` is not in the standard CSSProperties type;
preferred form: a small typed helper or a single comment explaining
the cast.

**Browser support:**

- Chrome / Edge / Opera: supported via `-webkit-text-security`
- Safari: supported (native to WebKit)
- Firefox 111+ (released March 2023): supported
- Older Firefox: would render as plain text — accepted risk; we don't
  support truly ancient browsers.

**Trade-off accepted:** The field is no longer a real password input,
so OS-level password-manager integration won't work. For API keys
this is preferred.

**Affected files (confirmed by grep for `type="password"` in
`frontend/src/app/components/llm-providers/`):**

- `adapter-views/CommunityView.tsx:118`
- `adapter-views/OllamaHttpView.tsx:165`
- `adapter-views/XaiHttpView.tsx:89`

**Out of scope:** The login form's password field and the
ChangePasswordPage. Those are real password inputs — leave them as
`type="password"` so password managers still work for them.

**Acceptance:** Entering an API key in any of the three adapter
config views does not trigger Chrome / Safari / Firefox to offer
"save password" or autofill. Value is still masked as dots.

---

### Item 5 — Rename option in chat-history items

**Current state:** `frontend/src/app/components/sidebar/HistoryItem.tsx`
has a `···` overflow menu with Pin/Unpin and Delete. Testers want to
rename history items to something memorable.

**Change:**

- Add a "Rename" menu entry between Pin/Unpin and Delete.
- Clicking it switches the title in the row to an inline `<input>`
  (existing styling, matched to the current `<span>` size and
  colour).
- Enter saves; Escape cancels; blur saves.
- Empty / whitespace-only title rejects the save and keeps the
  previous title.
- Calls the existing chat-session-rename API. Confirmed available:
  `frontend/src/core/api/chat.ts:210` `updateSession(sessionId, {
  title })` and the backend HTTP handler in
  `backend/modules/chat/_handlers.py:349`. The handler also publishes
  `ChatSessionTitleUpdatedEvent` so other open clients pick up the
  rename via WS.

**Acceptance:** Right-click / `···` menu offers Rename. The chat-list
title updates immediately on save and is persisted.

---

### Item 6 — iPhone PWA: top menu hidden behind the iOS status bar

**Reported by:** External tester on iPhone, in the installed PWA.

**Current state:**

- `frontend/index.html`: viewport meta has `viewport-fit=cover`,
  `apple-mobile-web-app-status-bar-style=black-translucent`. Both
  correct — they cause iOS to draw the app *under* the translucent
  status bar.
- Several pages already pad with `env(safe-area-inset-bottom)` (login,
  register, change-password, chat-input, mobile toast container).
- **No element pads with `env(safe-area-inset-top)`.** That is the
  bug: the top of the app overlaps the iOS status bar.

**Change:**

- Add `pt-[env(safe-area-inset-top)]` (or
  `pt-[max(<existing>,env(safe-area-inset-top))]` where existing
  padding matters) to the topmost mobile-visible elements:
  - `MobileSidebarHeader.tsx` (the 50px-tall top bar of the mobile
    sidebar)
  - The persona-overlay header (it's a full-screen overlay below `lg`)
  - The user-modal header
  - Any other full-screen mobile-only header that appears at top:0.
- Audit during planning: grep for `lg:hidden` headers and full-screen
  overlays, list them in the plan, fix them all in one pass.

**Acceptance:** After redeploying and reinstalling the PWA on iPhone,
the iOS status bar no longer occludes the top menu. Verified by the
reporting tester.

**Verification note:** We have no iPhone in the dev loop. The plan
should include a clear request to the reporting tester to re-verify
on the next deploy.

---

### Item 7 — iPhone PWA: tap-to-zoom on chat input + screen panning

**Reported by:** External tester on iPhone, in the installed PWA.

**Current state:**

- The chat-input textarea uses class `chat-text`, which inherits
  `--chat-font-size: 14px` (set in `frontend/src/index.css:34`).
- iOS Safari **always** zooms in on any input/textarea whose computed
  font-size is below 16px, then leaves the user stranded zoomed-in.
- The viewport meta already has `interactive-widget=resizes-content`,
  which is the modern correct hint. So the secondary symptom — "I
  need to drag right or zoom out" — is itself caused by the font-size
  trigger, not by viewport configuration.

**Change:**

- Force the chat input textarea (and any other input the user types
  into on mobile) to ≥ 16px on screens below `lg`.
- Cleanest: in `index.css`, add a media query
  `@media (max-width: 1023.98px) { input, textarea { font-size: 16px;
  } }`. Targeted enough that it doesn't fight the `chat-text` look
  for chat *messages* (which use `<p>`/`<div>`, not `<input>`).
- Or, narrower: only target the chat-input textarea and the user-bubble
  edit textarea. But the global rule is safer — any future input on
  mobile gets the right size by default.
- Recommend the global form-control rule.

**Acceptance:** After redeploy, focusing the chat input on iPhone does
not zoom the page. The Send button stays reachable. Verified by the
reporting tester.

**Note:** Desktop / `lg+` chat font-size remains 14px. Only mobile
form controls are bumped.

---

## File-Level Summary

**Modified:**

- `frontend/src/app/components/user-modal/PersonasTab.tsx` — Item 2
- `frontend/src/app/components/persona-card/AddPersonaCard.tsx` — Item 3
- `frontend/src/app/pages/PersonasPage.tsx` — Item 3 (remove menu state)
- `frontend/src/app/components/sidebar/HistoryItem.tsx` — Item 5
- `frontend/src/app/components/llm-providers/adapter-views/CommunityView.tsx` — Item 4
- `frontend/src/app/components/llm-providers/adapter-views/OllamaHttpView.tsx` — Item 4
- `frontend/src/app/components/llm-providers/adapter-views/XaiHttpView.tsx` — Item 4
- `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx` — Item 6
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — Item 6 (header pt)
- `frontend/src/app/components/user-modal/UserModal.tsx` — Item 6 (header pt), confirm during planning
- `frontend/src/index.css` — Item 7 (mobile form-control min font-size)
- Item 1: file(s) discovered during reproduction.

**Deleted:**

- `frontend/src/app/components/persona-card/AddPersonaMenu.tsx` — Item 3

**Tests touched:**

- `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`
  — extended for Item 2 (Import button present, fires file picker).
- `frontend/src/app/components/sidebar/Sidebar.test.tsx` /
  HistoryItem-related tests — Item 5 (Rename flow).
- `frontend/src/app/components/persona-card/AddPersonaCard.tsx` —
  add tests for the split halves; existing AddPersonaMenu tests are
  removed with the file.

---

## Risks & Open Questions

- **Item 1 root cause is unknown.** Implementation has to start with
  reproduction. If the bug turns out to be deeper than expected (e.g.
  state-management redesign needed), it should be split out into its
  own fix and the rest of the bundle continues without it.
- **Items 6 and 7 are blind to us.** Best-effort, verified by the
  reporting tester post-deploy.

## Manual verification (pre-merge)

Run all of these on your dev machine before merging — Items 6 and 7
additionally need iPhone verification post-deploy by the reporting
tester.

- [ ] **Item 1:** Open user-modal → Personas tab → click
      "+ Create persona". User-modal closes; persona-overlay opens
      with Edit tab focused; you can type a name and save. Saving
      switches to the new persona's Overview tab.
- [ ] **Item 2:** Same tab — click "Import" left of
      "+ Create persona". File picker opens; selecting a valid
      `.chatsune-persona.tar.gz` archive imports it; user-modal
      closes; you land on the new persona's Overview tab.
- [ ] **Item 3:** On the personas grid, the Add card shows two
      stacked halves. Top click → new-persona Edit overlay; bottom
      click → file picker. No popover menu appears anywhere.
- [ ] **Item 4:** Open any LLM-connection edit modal (Community,
      Ollama HTTP, xAI HTTP). Focus the API-key field. Browser does
      not offer to autofill or save a password. Value is masked as
      dots.
- [ ] **Item 5:** In the chat-history sidebar, open a session's `···`
      menu. Click Rename → inline editor. Enter new name, press
      Enter. List updates. Reload the page → new name persists.
      Esc cancels. Empty title is rejected.
- [ ] **Item 7 (desktop sanity):** Chat font size unchanged on `lg+`
      (still 14px in chat messages). Mobile inputs are ≥ 16px (look
      at the chat input on a narrow window — text larger than chat
      bubble text).
- [ ] **Items 6 & 7 (iPhone, by tester):** PWA top menu no longer
      hidden behind the iOS status bar. Tapping the chat input no
      longer zooms the page.
