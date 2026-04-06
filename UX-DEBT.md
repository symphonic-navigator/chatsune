# UX Debt

Generated: 2026-04-05. Covers all files under `frontend/src/`.

---

## 1. Independently Fixable (frontend-only changes)

---

### Critical / High Urgency

#### Low Effort

**[UX-001] Login fields labelled "Omen" and "Incantation" instead of "Username" and "Password"** — PARTIALLY FIXED

- File: `frontend/src/app/pages/LoginPage.tsx:51-66`
- Problem: The label texts for the login fields are "Omen" (username) and "Incantation" (password). A new user will not understand what to enter. There are no `placeholder` texts, no `autocomplete` attributes, and no semantically recognisable purpose.
- Why it matters: New users will be stuck at the first login. Missing `autocomplete="username"` and `autocomplete="current-password"` also means browser password managers will not work.
- Fix: Change labels to "Username" and "Password". Creative names can appear as subtitle under the logo, but not as field labels. Add `autocomplete` attributes.
- **Status:** `autocomplete` attributes added to all form fields (login + setup). Labels "Omen" and "Incantation" are **intentional by design** and must not be changed.

---

**[UX-002] No toast/notification display despite a fully implemented store**

- File: `frontend/src/core/store/notificationStore.ts:1-44`, `frontend/src/app/layouts/AppLayout.tsx` (no rendering present)
- Problem: There is a complete `notificationStore` with `addNotification` and `dismissToast` functions, but no UI component renders these notifications. Users never receive visual feedback for silent successes and errors.
- Why it matters: Actions like "password reset", "user deleted" and similar have no visible result unless the user checks the table. This completely violates the feedback principle.
- Fix: Create a `<ToastContainer />` component and include it in `AppLayout.tsx` that consumes notifications from the store and displays them as temporary toasts.
- **Status:** Fixed — `Toast.tsx` and `ToastContainer.tsx` components created, integrated into `AppLayout.tsx`. Toasts auto-dismiss with pause-on-hover and manual dismiss.

---

**[UX-003] Context menu in HistoryItem does not close when navigating to another session** — FIXED

- File: `frontend/src/app/components/sidebar/HistoryItem.tsx:36-46`
- Problem: The dropdown menu only closes on outside click (mousedown handler). If navigation happens via keyboard or programmatically, the menu stays open and can block interactions.
- Fix: Call `setMenuOpen(false)` on route change (`useEffect` with `location`).
- **Status:** Fixed — useEffect with useLocation closes menu and confirm state on route change.

---

**[UX-004] Destructive action "Delete Session" has no undo capability**

- File: `frontend/src/app/components/sidebar/HistoryItem.tsx:118-138`, `frontend/src/app/components/sidebar/Sidebar.tsx:305-312`
- Problem: The two-step confirmation menu ("Delete" -> "Confirm delete?") offers no undo after deletion. Once deleted, the entire chat history is irrecoverably gone. The two-step confirmation is small and hidden in the hover state -- easily triggered accidentally.
- Why it matters: Accidental deletion is permanent.
- Fix: After deletion, show a brief toast with an "Undo" button (e.g. 5 seconds) that restores the session. Alternatively: implement a "Recycle Bin" logic in the backend.

---

**[UX-005] UserModal tab bar is not scrollable -- tabs get cut off on narrow viewports** — FIXED

- File: `frontend/src/app/components/user-modal/UserModal.tsx:121-139`
- Problem: The tab bar has `flex` and `px-4`, but no `overflow-x-auto`. With 10 tabs ("About me", "Projects", "History", "Knowledge", "Bookmarks", "Uploads", "Artefacts", "Models", "Settings", "API-Keys"), on smaller screens or with the sidebar open, the rightmost tabs are invisibly cut off.
- Why it matters: The "API-Keys" tab with the red error indicator is often the last tab and may be unreachable on smaller window widths.
- Fix: Add `overflow-x-auto` to the tab bar. Or: wrap tabs into two rows or use a dropdown for overflow tabs.
- **Status:** Fixed — `overflow-x-auto` added to tab bar container.

---

#### Medium Effort

**[UX-006] PersonaCard has invisible click zones -- no visual hint for "Continue" vs. "New"** — FIXED

- File: `frontend/src/app/components/persona-card/PersonaCard.tsx:191-245`
- Problem: The card has two invisible click zones (left 2/3 for "Continue", right 1/3 for "New"), only visible on hover with very faint text. A user clicking without hovering first has no idea what will happen. The divider line is also only visible on hover.
- Why it matters: Violates the principle of predictability. A click on the left side and a click on the right side have completely different effects, without this being apparent.
- Fix: Make the split permanently more visible -- e.g. a subtle vertical divider always visible, or move the actions to the menu bar at the bottom (which already contains "Overview / Edit / History").
- **Status:** Fixed — entire card body is now a single "Continue" click target with hover hint. "New Chat" is an explicit icon button in the menu bar. Menu bar uses SVG icons instead of text. Model name displayed below tagline.

---

**[UX-007] No loading spinner during session resolution on first chat load**

- File: `frontend/src/features/chat/ChatView.tsx:43-75`, `frontend/src/features/chat/ChatView.tsx:321-327`
- Problem: When the user clicks a persona and `/chat/:personaId` is called (without session ID), `chatApi.listSessions()` and potentially `chatApi.createSession()` run. During this time the UI may show an empty chat area without clear feedback.
- Fix: Introduce a dedicated `isResolvingSession` state and show a spinner during resolution.
- **Status:** Fixed — `resolvingSession` ref replaced with `isResolvingSession` state, spinner shown with "Resolving session..." text during resolution.

---

**[UX-008] Copy and bookmark actions on messages are only visible on hover and positioned outside the message area**

- File: `frontend/src/features/chat/AssistantMessage.tsx:35-61`, `frontend/src/features/chat/UserBubble.tsx:64-82`
- Problem: Copy and bookmark buttons only appear in hover state and position themselves absolutely outside the message bubble (`-right-8` and `-left-8`). On touch devices there is no hover state. On narrow screens these buttons may be outside the visible area.
- Why it matters: On touch devices the actions are completely unreachable.
- Fix: Position actions inside the message bubble and show on tap/hover, or build a permanently visible action strip under each message.

---

#### High Effort

**[UX-009] Sidebar in collapsed mode opens UserModal for "Projects", "History", etc., while expanded mode shows these as inline sections -- inconsistent navigation paradigm**

- File: `frontend/src/app/components/sidebar/Sidebar.tsx:375-419` (collapsed), `frontend/src/app/components/sidebar/Sidebar.tsx:598-733` (expanded)
- Problem: In expanded sidebar mode, "Projects" and "History" are shown as collapsible sections directly in the sidebar. In collapsed mode, the same actions open the `UserModal`. These are two fundamentally different interaction patterns for the same function.
- Fix: Choose a consistent model -- either always modal, or always sidebar section. The expanded sidebar variant (inline sections) is the better UX.

---

### Medium Urgency

#### Low Effort

**[UX-010] "GEN" button for title generation shows only "..." during wait -- no clear status**

- File: `frontend/src/app/components/user-modal/HistoryTab.tsx:319-325`, `frontend/src/app/components/persona-overlay/HistoryTab.tsx:239-244`
- Problem: After clicking "GEN", the button text changes to "..." for 2 seconds (hard-coded timeout), regardless of whether the title was actually generated. The response is event-driven -- there is no real feedback on success or failure.
- Fix: Reset button to "GEN" when a `session.title` update event arrives for this session, or use a tooltip "Generating..." + icon spinner.
- **Status:** Fixed — static "..." replaced with animated spinner, opacity raised to 60% for visibility. Event-driven reset logic was already correct.

---

**[UX-011] "SURE?" confirmation button for deletion disappears after 3 seconds without feedback**

- File: `frontend/src/app/components/sidebar/HistoryItem.tsx:33`, `frontend/src/app/components/user-modal/HistoryTab.tsx:250-254`, `frontend/src/app/components/user-modal/BookmarksTab.tsx:277-281`
- Problem: The 3-second timeout for the delete confirmation simply disappears without telling the user the action was cancelled. If the user was waiting to click "SURE?", they only see that the button vanished.
- Fix: Either remove the timeout, or add a visual progress indicator (e.g. a shrinking border). Closing on outside-click is better.

---

**[UX-012] Missing `aria-label` attributes on toggle elements in EditTab** — FIXED

- File: `frontend/src/app/components/persona-overlay/EditTab.tsx:403-449`
- Problem: The `Toggle` component is a `div` with `onClick`, but has no `role="switch"`, no `aria-checked`, and no `aria-label`. The visual toggle switch itself is a non-interactive `div`.
- Why it matters: Screen reader users cannot read the toggle states. Keyboard navigation is not possible.
- Fix: Add `role="switch"`, `aria-checked={value}`, `aria-label={label}` to the outer `div` and add `tabIndex={0}` + `onKeyDown` handler.
- **Status:** Fixed — role, aria-checked, aria-label, tabIndex, and onKeyDown added.

---

**[UX-013] Date formatting in HistoryTab uses "de-DE" locale in an English-language UI** — FIXED

- File: `frontend/src/app/components/sidebar/HistoryItem.tsx:6-13`, `frontend/src/app/components/user-modal/HistoryTab.tsx:39-44`, `frontend/src/app/components/persona-overlay/HistoryTab.tsx:39-44`
- Problem: The `formatSessionDate` function uses `"de-DE"` as locale, producing German date formats (e.g. "12. Apr, 14:30"). The rest of the UI is in English. Inconsistent for non-German users.
- Fix: Use `undefined` as locale (browser default) or derive from user settings. Alternatively use a consistent format like "12 Apr 14:30".
- **Status:** Fixed — all three files now use `undefined` (browser default locale).

---

**[UX-014] `ContextStatusPill` shows only a green dot without any information in normal state**

- File: `frontend/src/features/chat/ContextStatusPill.tsx:16-29`
- Problem: In `green` state, the pill shows only a green dot -- no percentage, no label, no automatically visible tooltip text. A user wondering "What is that green thing?" gets no information without hovering.
- Fix: In `green` status, show either a minimal label ("CTX") or an always-visible tooltip-like hint. Or remove the element entirely until the context is no longer green.

---

**[UX-015] Reasoning toggle: no visual difference between "not supported" and "manually off"** — ALREADY FIXED

- File: `frontend/src/features/chat/ToolToggles.tsx:57-77`
- Problem: When `modelSupportsReasoning` is false, the button is disabled (`disabled:opacity-40`). When reasoning is manually turned off at a supported model, the button looks identical. The tooltip differs, but only on hover.
- Fix: Clear visual distinction -- e.g. for unsupported models use strikethrough text or a lock icon, rather than just `opacity-40`.
- **Status:** Already fixed — the reasoning button is only rendered when `modelSupportsReasoning` is true. When the model doesn't support reasoning, the button is not shown at all.

---

#### Medium Effort

**[UX-016] "Other Personas" dropdown starts closed by default -- new users may see an empty sidebar**

- File: `frontend/src/app/components/sidebar/Sidebar.tsx:159-167`
- Problem: The `unpinnedOpen` state starts as `false` (unless localStorage says otherwise). If a user has personas that are all unpinned, they see "No pinned personas" and nothing else -- the other personas are hidden behind a very small "Other Personas 3" element.
- Why it matters: New users who have not pinned any personas see an empty sidebar and may think there are no personas. Very misleading for first-time use.
- Fix: Default to `unpinnedOpen: true` when no personas are pinned. Or: if no personas are pinned, show all personas directly without dropdown.
- **Status:** Fixed — defaults to open when no personas are pinned, auto-opens when last persona is unpinned, respects explicit localStorage preference.

---

**[UX-017] PersonaOverlay shows "Knowledge", "Memories", and "History" tabs during creation, though content does not exist**

- File: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx:161-188`
- Problem: The tab bar shows all 5 tabs during persona creation. The tabs "Overview", "Knowledge", "Memories", "History" render nothing (they return `null` since `isCreating` is true), but the buttons are still clickable.
- Fix: During `isCreating = true`, only show the "Edit" tab, or mark others as disabled with a tooltip "Available after creation".
- **Status:** Fixed — tabs filtered to show only "Edit" tab when `isCreating` is true.

---

**[UX-018] Paste behaviour: text over 500 characters is automatically treated as a file attachment, without asking**

- File: `frontend/src/features/chat/ChatInput.tsx:48-65`
- Problem: When the user pastes text with more than 500 characters, it is automatically added as a `pasted-text.txt` file and removed from the input field. The user may intend to use the text directly in the chat.
- Why it matters: This significantly violates the Principle of Least Astonishment. The pasted text "disappears" from the input field and appears as an attachment -- completely unexpected behaviour.
- Fix: Show a notification/confirmation: "This text is long. Attach as file or include directly?" Or: show a clear hint with a button "Convert to text file", rather than doing it automatically.

---

#### High Effort

**[UX-019] Two separate "History" entry points with different feature sets: sidebar inline vs. UserModal**

- File: `frontend/src/app/components/sidebar/Sidebar.tsx:623-697` (sidebar history), `frontend/src/app/components/user-modal/HistoryTab.tsx` (modal history)
- Problem: The sidebar shows a simple session list with Pin/Unpin/Delete. The UserModal "History" tab shows the same with additional search field, persona filter, Rename (REN), Generate Title (GEN) and more. The duplication is confusing.
- Why it matters: Users must learn that the "real" history management is in the modal, not in the sidebar. This is not intuitive.
- Fix: Establish consistency -- either all history actions in the sidebar, or all in the modal with the sidebar showing only a preview with an "Open full history" link.

---

### Low Urgency

#### Low Effort

**[UX-020] Model name in Topbar is split by ":" -- only the part after the first colon is shown** — ALREADY FIXED

- File: `frontend/src/app/components/topbar/Topbar.tsx:109`
- Problem: `.split(":")[1]` -- if the model ID has multiple colons (e.g. `ollama_cloud:deepseek-r1:70b`), only `deepseek-r1` is shown, not `deepseek-r1:70b`.
- Fix: Use `.split(":").slice(1).join(":")`, consistent with the pattern used in `EditTab.tsx:32`.
- **Status:** Already fixed — Topbar.tsx already uses `.split(":").slice(1).join(":")`.

---

**[UX-021] "Sanitised" toggle in the sidebar has no label in collapsed mode** — FIXED

- File: `frontend/src/app/components/sidebar/Sidebar.tsx:424-431`
- Problem: In collapsed mode, the sanitised toggle is only a lock emoji. The `title` attribute says "Sanitised mode on" or "Sanitised mode off" -- describing the current state, not the action.
- Fix: Change `title` to "Turn sanitised mode on/off" or "Sanitised mode: on/off (click to toggle)".
- **Status:** Fixed — title now describes the action ("Click to turn sanitised mode on/off").

---

**[UX-022] UploadBrowserPanel shows all files for a user, not just those for the current persona**

- File: `frontend/src/features/chat/UploadBrowserPanel.tsx:16-21`
- Problem: The API is called with `{ persona_id: personaId }`, but `personaId` is optional and can be `undefined`. In incognito chats there is no `personaId`, which leads to all files being displayed without filtering.
- Why it matters: In NSFW personas or sanitised mode, files from other personas may be visible.
- Fix: In incognito mode, disable the upload browser panel or show an empty state.
- **Status:** Fixed — API call skipped in incognito mode, empty state message shown instead.

---

**[UX-023] "White Script" settings in SettingsTab have no preview**

- File: `frontend/src/app/components/user-modal/SettingsTab.tsx:92-108`
- Problem: The settings for Chat Font, Font Size and Line Spacing have no live preview area. Changes affect the chat in the background, but the user cannot see the effect directly in the settings modal.
- Fix: Add a small preview text block under the settings that is formatted with the selected values.

---

#### Medium Effort

**[UX-024] PersonaCard in DragOverlay shows the full card with real onClick handlers** — FIXED

- File: `frontend/src/app/pages/PersonasPage.tsx:99-111`
- Problem: During a drag operation, the `DragOverlay` shows a real `PersonaCard` instance (not just a ghost) with `onContinue={() => {}}` and `onNewChat={() => {}}` as empty functions. The card is interactive, but the actions do nothing.
- Fix: Use a dedicated, lightweight drag ghost component, or add `pointer-events: none` to the DragOverlay content.
- **Status:** Fixed — `pointerEvents: "none"` added to DragOverlay wrapper.

---

**[UX-025] Deleting the active session navigates away without clear feedback**

- File: `frontend/src/app/components/sidebar/Sidebar.tsx:305-312`
- Problem: `handleDeleteSession` deletes the session and navigates to `/personas` if it was active. This happens without warning: the user suddenly sees the personas page without knowing why.
- Fix: After deleting an active chat, provide clearer feedback (toast: "Chat deleted. You've been redirected to Personas.").
- **Status:** Fixed — toast notification with session title and "Undo" action button shown on deletion.

---

## 2. Requires Backend Coordination

---

### Critical / High Urgency

#### Low Effort

**[UX-026] No recovery path when a chat error occurs and `recoverable: false`**

- File: `frontend/src/features/chat/ChatView.tsx:372-386`
- Problem: When `error.recoverable === false`, the UI shows the error message with only a "Dismiss" button. There is no way to return to the last working state or start a new session, other than manual navigation.
- Fix (frontend): Add a "Start new chat" button for the `recoverable: false` case. Fix (backend): Ensure the error event provides enough context for the frontend to offer recovery options.

---

**[UX-027] `session_expired` error redirects the user to a new chat without notification**

- File: `frontend/src/features/chat/ChatView.tsx:201-207`
- Problem: When a `session_expired` error event arrives, the user is silently redirected to a new chat. The previous chat history is still in the database, but the user has no idea what just happened and why they are suddenly in an empty chat.
- Fix: Before navigation, show a toast: "Your session has expired. Starting a new chat." and link to the old chat ("View previous chat").

---

### Medium Urgency

#### Medium Effort

**[UX-028] Incognito mode has no visual separation between different persona incognito sessions**

- File: `frontend/src/features/chat/ChatView.tsx:39-41`, `frontend/src/features/chat/ChatView.tsx:332-337`
- Problem: The `incognitoIdRef` generates a new ID on each navigation. But if the user uses two different personas in incognito mode, there is no distinction -- only the "INCOGNITO" badge in the header. The chat ID is invisible to the user.
- Fix: More clearly communicate in incognito mode: "This conversation will not be saved. A new session starts each time." on first open.

---

**[UX-029] Bookmark scope "Local" vs. "Global" is unclear without context explanation**

- File: `frontend/src/features/chat/BookmarkModal.tsx:101-135`
- Problem: The scope selection has a short explanation, but "local" bookmarks appear neither in the global bookmark list nor in the sidebar -- they are only visible in this chat and completely disappear when switching chats.
- Why it matters: A user who chooses "Local" and later searches for the bookmark cannot find it in the global bookmark list.
- Fix: Default to "Global" (the more useful behaviour). Or: make the explanation more concrete: "Local: only visible in this chat. Cannot be found via Bookmarks sidebar."

---

### Low Urgency

#### Low Effort

**[UX-030] Memory tokens and pending journal in OverviewTab always show a dash** — FIXED

- File: `frontend/src/app/components/persona-overlay/OverviewTab.tsx:127-145`
- Problem: The stats grid shows "Memory tokens" and "Pending journal" with hard-coded dash values. The memory module is not yet implemented, but the placeholders are styled as real data points, giving the impression that data is loading or missing.
- Fix: Hide these stats fields until the memory module is implemented, or replace with a clear "Coming soon" label.
- **Status:** Fixed — removed "Memory tokens" and "Pending journal" stats, only "Chats" remains.

---

**[UX-031] MemoriesTab shows "memory entries -- coming with the memory module" -- inconsistent placeholder style** — FIXED

- File: `frontend/src/app/components/persona-overlay/MemoriesTab.tsx:9-17`
- Problem: The placeholder text is in lowercase monospace, looking like debug text. The tab itself is visible in the tab bar with the mystical "anahata" subtitle.
- Fix: Introduce a consistent placeholder style for all unfinished features -- e.g. an icon plus "This feature is coming soon." in consistent styling.
- **Status:** Fixed — consistent placeholder with chakra-coloured icon and "This feature is coming soon." text.
