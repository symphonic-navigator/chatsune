# UX Debt — Chatsune Frontend

A UX-only audit of `/frontend/src`. Focus: user experience, not code quality.
Findings are split into work that can be fixed autonomously and items that require
a product decision from Chris.

Legend: **Impact** / **Effort** / **Risk** = high / med / low.

---

## Autonom lösbar

### Feedback / Loading / Empty / Error States

- [x] **Login form: no inline field validation** — `app/pages/LoginPage.tsx:48-94`. Only the generic "Invalid username or password" appears after submit; no per-field hints, no caps-lock warning, no rate-limit feedback. Impact: med / Effort: low / Risk: low.
- [x] **Login labels are themed but not accessible** — `LoginPage.tsx:50` ("Omen", "Incantation"). Cute, but no `htmlFor`/`id` linkage and no `aria-label` fallback; screen readers say nothing meaningful. Impact: med / Effort: low / Risk: low.
- [x] **Loading text is invisible-grade** — e.g. `ChatView.tsx:367,459` uses `text-white/20` for "Loading messages…". Below WCAG contrast and easy to miss. Impact: med / Effort: low / Risk: low.
- [x] **Generic catch-and-swallow on critical fetches** — `ChatView.tsx:181,188,211` use `.catch(() => {})`. User sees nothing if message history, artefacts or session metadata fail to load. Add a visible empty/error fallback. Impact: high / Effort: low / Risk: low.
- [x] **Session resolve has no timeout** — `ChatView.tsx:53-85,361-372`. If `listSessions`/`createSession` hangs, the spinner spins forever with no cancel/retry. Impact: med / Effort: low / Risk: low.
- [ ] **No empty-state component family** — only ~15 files mention "empty/none/no data" patterns; most lists (history, bookmarks, knowledge, artefacts, projects, uploads) just render nothing when empty. Add a consistent illustrated empty state per tab. Impact: high / Effort: med / Risk: low.
- [x] **Title-generation 10s fallback** (persona-overlay HistoryTab: error notice + aria-live) — `persona-overlay/HistoryTab.tsx:222-227` silently resets `generating` after 10s with no error feedback. User has no idea if it failed. Impact: low / Effort: low / Risk: low.
- [x] **Avatar copy fail is silent** (admin-modal UsersTab: inline aria-live error notice) — `admin-modal/UsersTab.tsx:78` swallows clipboard errors. Add a toast. Impact: low / Effort: low / Risk: low.
- [x] **`Toast.tsx` only used in 3 files for "title=" tooltips** (partial: Sidebar/PersonaCard/PersonaItem/NavRow/ChatInput) — most icon-only buttons across the app have no tooltip at all (see PersonaItem, NavRow, sidebar action buttons, ChatInput icons). Add `title`/tooltip pass. Impact: med / Effort: med / Risk: low.

### Accessibility (a11y)

- [x] **Almost no `aria-label`s** (partial: Sidebar/PersonaCard/PersonaItem/ChatInput/persona-overlay) — only ~32 occurrences across 18 files in `app/`; most icon-only buttons (sidebar pin/delete, chat header bookmark/context, persona card actions, dropdown carets, modal close ×, copy buttons) are unlabelled. Impact: high / Effort: med / Risk: low.
- [~] **Form inputs miss `htmlFor`/`id`** (DONE: persona EditTab, LibraryEditorModal, DocumentEditorModal, ApiKeysTab EditRow via `useId`) — login, setup, NewUserForm still pending. Impact: high / Effort: low / Risk: low.
- [x] **Custom toggle is a `div` with `onClick`** (persona-overlay EditTab Toggle: now real `<button role="switch">` with keyboard handler) — `persona-overlay/EditTab.tsx:417`. Impact: high / Effort: low / Risk: low.
- [x] **Tab components likely lack `role="tablist"`/`role="tab"`** (DONE: PersonaOverlay, AdminModal, UserModal). Impact: med / Effort: low / Risk: low.
- [~] **Modals lack focus trap / `aria-modal`** (DONE: ModelConfigModal, AvatarCropModal, BookmarkModal, LibraryEditorModal, CurationModal via `useFocusTrap` hook with focus restoration + aria-labelledby; PersonaOverlay + UserModal already have `role="dialog"` + `aria-modal="true"`; DocumentEditorModal now has `role="dialog"` + `aria-modal="true"` + `aria-label`) — AdminModal still pending; UserModal/DocumentEditorModal focus-trap hook integration pending (other agent). Impact: high / Effort: med / Risk: low.
- [x] **No global skip-link / landmark roles** (AppLayout) — `AppLayout.tsx`. Add `<main>`/`<nav>` and a skip-to-content link. Impact: med / Effort: low / Risk: low.
- [x] **Colour-contrast across the dark theme** (partial: Sidebar/ChatInput functional text raised to /60) — heavy use of `text-white/20`, `text-white/25`, `text-white/30` for actual content (not decorative). Fails WCAG AA. Impact: high / Effort: med / Risk: low.
- [x] **Hover-only action reveal** (PersonaItem: focus-within added) — sidebar HistoryItem actions appear with `opacity-0 group-hover:opacity-100` (`HistoryTab.tsx:278`). Inaccessible by keyboard and invisible on touch. Add `focus-within:opacity-100` and persistent affordance on touch. Impact: high / Effort: low / Risk: low.

### Keyboard navigation

- [x] **No global Esc-to-close convention** — only some modals close on Esc; verify and unify across all overlays. Impact: med / Effort: low / Risk: low. _Audited all overlays (2026-04-07); added reusable `useEscapeKey` hook and fixed `JournalDropdown`. All other modals already supported Esc._
- [ ] **No documented shortcut surface** — `Shift+Esc` to focus chat input is implemented (`ChatView.tsx:215-224`) but undiscoverable. Add a `?` shortcut help overlay. Impact: med / Effort: med / Risk: low.
- [ ] **Sidebar navigation not keyboard-traversable** — items rely on click handlers without arrow-key navigation. Impact: med / Effort: med / Risk: low.
- [ ] **Drag-and-drop has no keyboard alternative** — bookmark/persona/session reordering via dnd-kit has no `aria-keyshortcuts` fallback. Impact: med / Effort: med / Risk: low.

### Destruktive Aktionen

- [~] **3-second "SURE?" pattern is fragile** — DEL/SURE in user-modal `ApiKeysTab`, `HistoryTab`, `BookmarksTab` are now real `<button>`s with `aria-label`, `title` and `aria-live` announcement. `persona-overlay/HistoryTab.tsx` still pending. Impact: high / Effort: med / Risk: low.
- [ ] **Session delete already supports Undo (good)** — `Sidebar.tsx:354-384`. Apply the same pattern to: persona delete, bookmark delete, knowledge document delete, library delete, API-key delete, user delete. Impact: high / Effort: med / Risk: low.
- [x] **DocumentEditorModal uses native `window.confirm`** — replaced with inline two-step "Cancel → Discard?" pattern + `aria-live` announcement (user-modal scope).
- [ ] **No "delete" affordance on persona cards is invisible** — verify destructive paths on PersonaCard / AddPersonaCard show clearly what will be lost (sessions, memories, journal). Impact: high / Effort: med / Risk: med.

### Forms & Validation

- [x] **No client-side validation messages** — Setup form (`LoginPage.tsx:97-207`) accepts anything; relies entirely on backend errors. No password strength meter, no email format hint, no PIN format hint. Impact: med / Effort: low / Risk: low.
- [ ] **`required` attribute is the only validation** — used everywhere; browsers show native bubbles that clash with the dark theme. Impact: low / Effort: med / Risk: low.
- [~] **No "unsaved changes" guard on most editors** (DONE: LibraryEditorModal + BookmarkModal via `useUnsavedChangesGuard` hook with inline themed prompt) — EditTab (persona), NewUserForm, DocumentEditorModal (replace `window.confirm`) still pending. Impact: high / Effort: med / Risk: low.
- [ ] **No character/length counters** — persona description, bookmark titles, knowledge documents, system prompts have no live counter; truncation only visible after save. Impact: low / Effort: low / Risk: low.
- [ ] **Field error placement inconsistent** — login shows a single block; ApiKeysTab shows inline; UsersTab shows top-of-form. Standardise. Impact: low / Effort: med / Risk: low.

### Mobile / Responsive

- [ ] **Almost no responsive breakpoints** — only ~16 `md:`/`sm:`/`lg:` usages in all of `app/components`. Sidebars (`Sidebar.tsx:399` fixed `w-[50px]`), modals (`max-w-sm`-style fixed widths), persona overlays, chat input toolbars are all desktop-only. Impact: high / Effort: high / Risk: med.
- [x] **Chat header truncates persona title at fixed `max-w-[400px]`** — `ChatView.tsx:383`. Breaks on narrow screens. Impact: low / Effort: low / Risk: low.
- [ ] **Hover-only reveals (see a11y)** are unusable on touch. Impact: high / Effort: med / Risk: low.
- [ ] **Drag-and-drop lacks touch optimisation** — no long-press delay configured per pointer type. Impact: med / Effort: med / Risk: low.
- [ ] **Modals not full-screen on mobile** — they stay centred/`max-w-*` and overflow. Impact: high / Effort: med / Risk: low.

### Onboarding & Discoverability

- [ ] **No first-run tour** — after master-admin setup, user lands on `/personas` with zero guidance. Impact: med / Effort: med / Risk: low.
- [x] **Persona/tools/journal/incognito concepts are undocumented in-app** — INCOGNITO badge now has a click-to-open info popover explaining ephemeral mode (`ChatView.tsx`). Impact: med / Effort: low / Risk: low.
- [~] **API-key onboarding is hidden** — `ApiKeysTab` now shows a prominent "Add your first API key" panel with explanation when 0 keys are configured. Global gating outside the tab still pending.
- [~] **No empty-state CTAs** — Knowledge (existing), Bookmarks, Projects, Uploads, ApiKeys empty states now show explanatory text + CTA where applicable (user-modal scope).

### Microcopy / Labels

- [x] **Mystical labels obscure function** (login only — other surfaces TBD) — "Omen", "Incantation", "Cast", "Casting…" (`LoginPage.tsx`). Charming but blocks new users; at minimum add a small subtitle ("username", "password"). Impact: med / Effort: low / Risk: low.
- [x] **All-caps mono "REN / GEN / DEL / SURE?"** — `persona-overlay/HistoryTab.tsx`. `title` + `aria-label` tooltips added ("Rename session", "Regenerate title", "Delete session", "Confirm delete (click again)"). Impact: med / Effort: low / Risk: low.
- [~] **Error messages are generic** — `ApiKeysTab` messages reworded ("Could not delete API key. Please try again." etc.). Other surfaces still pending.

### Misc Flows

- [ ] **Session-expired flow is good but invisible if user is mid-typing** — `ChatView.tsx:227-247`. Toast may be missed; consider modal interrupt. Impact: low / Effort: low / Risk: low.
- [~] **Optimistic message has no failure rollback UI** — `ChatView.tsx:269-280`. TODO left in code; per-bubble retry needs MessageList plumbing, top-level error banner exists today. Impact: med / Effort: med / Risk: low.
- [x] **Cancel mid-stream has no confirmation of what was kept** — `ChatView.tsx:307-310`. Inline "partial response saved" notice now shown. Impact: low / Effort: low / Risk: low.

---

## Benötigt User-Entscheidung

These touch product/identity choices and should not be changed unilaterally.

- **Mystical/themed microcopy ("Omen", "Cast", "REN/GEN/DEL/SURE?", 🦊 emoji) vs. plain labels.** The opulent prototype style is intentional. Decision needed: keep flavour and add accessible subtitles/aria-labels, or replace flavour terms in primary flows and reserve them for secondary surfaces?
- **Destructive-confirmation pattern.** Three options: (a) keep "click twice within 3s" everywhere, (b) replace with modal confirm, (c) standardise on "act immediately + 8s undo toast" (already used for session delete). Which should be the canonical pattern?
- **Mobile support scope.** Currently desktop-only. Is mobile a target for Phase 1, Phase 2, or never? Drives whether to invest in responsive refactor.
- **Accessibility target.** WCAG 2.1 AA fully? Or "reasonable best-effort" given a single-user / self-hosted context? This decides how aggressively to fight the low-contrast `text-white/20` aesthetic.
- **Onboarding tour.** Add an interactive first-run walkthrough, or just a static "getting started" panel on the empty `/personas` page?
- **Incognito chat affordances.** Should the INCOGNITO badge open an explainer popover, or stay minimal?
- **Persona delete consequences.** What exactly should the confirm dialog warn about (sessions, memories, journal, knowledge bindings, bookmarks)? Needs product clarity before wording.
- **Error reporting verbosity.** Do users see correlation IDs / technical detail, or only friendly text? Affects every error UI.
- **Form validation strategy.** Trust backend (current) vs. mirror validation client-side (more code, faster feedback). Pick one and apply consistently.
- **Keyboard-shortcut surface.** Should Chatsune become a power-user keyboard app (cmd-palette, `?` overlay, j/k navigation), or stay mouse-first?

---

## Hot spots (highest pain per effort)

1. Add `aria-label`s + `htmlFor` bindings — one PR, huge a11y win.
2. Replace `text-white/20` in functional text with `text-white/55` or higher.
3. Make hover-only action reveals also `focus-within:`.
4. Standardise destructive confirmation (decision needed first).
5. Add real empty states with CTAs for Knowledge / Bookmarks / Projects / Uploads / API keys.
6. Add focus traps + Esc handling to all modals.
