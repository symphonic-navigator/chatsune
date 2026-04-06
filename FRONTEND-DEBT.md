# Frontend Technical Debt

Generated: 2026-04-05. Covers all files under `frontend/src/`.

---

## 1. Independently Fixable (no backend changes needed)

---

### Critical / High Urgency

#### Low Effort

**[FD-001] `useLlm` stale closure -- model refresh events never trigger re-fetches**

- File: `frontend/src/core/hooks/useLlm.ts:59-65`
- Problem: The `LLM_MODEL_CURATED` and `LLM_MODELS_REFRESHED` event handlers close over the initial `models` state (an empty `Map`). `models` is not in the `useEffect` dependency array, so after real model data is loaded, the handlers still iterate an empty map. Curating a model or triggering a model refresh silently does nothing to the in-memory model list.
- Why it matters: Admins curating models will not see the effect until they navigate away and back. The refreshed models list never appears without a page reload.
- Fix: Replace the `models.forEach(...)` inside the event handlers with a ref that always holds the current models map, or restructure so the handlers only call `fetchModels` with a known provider ID rather than iterating the closure-captured map.

---

**[FD-002] `useChatStream` constructs final message with a fake client-side ID**

- File: `frontend/src/features/chat/useChatStream.ts:66`
- Problem: When `CHAT_STREAM_ENDED` fires, the assistant message is stored with a timestamp-based ID. The real server-assigned message ID is not extracted from the event payload. All subsequent operations keyed by message ID -- `truncateAfter`, `deleteMessage`, `updateMessage`, bookmark lookup via `bookmarkedMessageIds` -- will silently fail for this message because none will find a match on the fake ID.
- Why it matters: Editing the last assistant message, regenerating, or bookmarking it immediately after streaming ends will not work correctly until the page is refreshed and real messages are loaded from the API.
- Fix: Extract the real message ID from `p.message_id` in `CHAT_STREAM_ENDED` and use it instead. If the backend does not yet send it, this requires backend coordination (see Section 2).

---

**[FD-003] `CroppedAvatar` broken `backgroundImage` in the no-crop branch**

- File: `frontend/src/app/components/avatar-crop/CroppedAvatar.tsx:40-42`
- Problem: The no-crop branch constructs `backgroundImage` with double `url()` nesting. The two `.replace()` calls attempt to fix this but only handle one level of nesting. The crop branch at line 83 correctly uses a single `url()` wrapper directly.
- Why it matters: Every persona avatar without a crop set will display as a broken image.
- Fix: Change the expression to use a single `url()` wrapper, matching the crop branch.

---

#### Medium Effort

**[FD-004] `usePersonas` and `useSettings` re-fetch full lists on every event -- violates event-first principle**

- Files: `frontend/src/core/hooks/usePersonas.ts:29-31`, `frontend/src/core/hooks/useSettings.ts:29-30`
- Problem: Every `PERSONA_CREATED`, `PERSONA_UPDATED`, `PERSONA_DELETED`, `SETTING_UPDATED`, and `SETTING_DELETED` event triggers a full API re-fetch instead of applying the event payload directly. CLAUDE.md states: "Events carry DTOs -- the frontend never makes a follow-up REST call to learn what changed."
- Why it matters: Each change generates an extra round-trip. State flickers (loading -> loaded) on every remote event, and the optimistic reorder in `usePersonas.reorder` is immediately overwritten when `PERSONA_UPDATED` fires and triggers a re-fetch.
- Fix: Apply the payload directly in the event handler. For personas: add/replace/remove the persona DTO from local state using `event.payload`. For settings: do the same with the setting DTO.

---

**[FD-005] `Topbar.tsx` component `LivePill` defined inside render scope**

- File: `frontend/src/app/components/topbar/Topbar.tsx:32`
- Problem: `const LivePill = () => (...)` is declared inside `Topbar`, creating a new function component type on every render. React treats it as a completely new component type each time and unmounts/remounts it, destroying local state and causing unnecessary DOM churn.
- Fix: Move `LivePill` to module scope and pass `isLive` and `wsStatus` as props.

---

#### High Effort

**[FD-006] `Record<string, Function>` used throughout DnD plumbing -- implicit `any`-equivalent**

- Files: `frontend/src/app/components/sidebar/PersonaItem.tsx:16`, `frontend/src/app/components/sidebar/HistoryItem.tsx:25`, `frontend/src/app/components/sidebar/Sidebar.tsx:96,114`, `frontend/src/app/components/user-modal/BookmarksTab.tsx:204,215`
- Problem: dnd-kit listener types are cast to `Record<string, Function>` throughout the drag-and-drop wiring. `Function` is a catch-all type with no parameter or return type safety -- functionally equivalent to `any`. CLAUDE.md explicitly prohibits `any` in TypeScript.
- Fix: Import `DraggableAttributes` and `SyntheticListenerMap` from `@dnd-kit/core` and use them as the prop types.

---

### Medium Urgency

#### Low Effort

**[FD-007] `markdownComponents.tsx` XSS risk in Shiki error fallback**

- File: `frontend/src/features/chat/markdownComponents.tsx:87-88`
- Problem: When `highlighter.codeToHtml` throws, the catch block falls back to inserting raw unescaped code string via innerHTML. If the code string contains malicious HTML tags, this is an XSS vector. The content should be sanitised with DOMPurify or escaped before insertion.
- Fix: HTML-escape the code string in the fallback path (replace `<`, `>`, `&`, `"`), or use DOMPurify to sanitise it, or wrap in a React element created via JSX rather than raw HTML.

---

**[FD-008] `useAutoScroll` programmatic scroll flag consumed by the wrong scroll event**

- File: `frontend/src/features/chat/useAutoScroll.ts:34-38`
- Problem: A boolean ref is set synchronously before `scrollIntoView`, but the resulting scroll event fires asynchronously. During rapid streaming, multiple `scrollIntoView` calls queue up. The flag is cleared on the *first* scroll event, so subsequent programmatic scrolls are mis-identified as user scrolls and stop auto-scroll mid-stream.
- Fix: Use a counter rather than a boolean flag: increment before each programmatic scroll, decrement on the next scroll event. Only set `userScrolledUpRef.current = true` when the counter is 0.

---

**[FD-009] `useWebSocket` double ping interval during rapid auth state toggling**

- File: `frontend/src/core/hooks/useWebSocket.ts:14-28`
- Problem: If `isAuthenticated` transitions `false -> true -> false` faster than React batching (e.g. during token refresh), a ping interval from the first `true` state may not be cleaned up before a new one is started.
- Fix: Use a ref to hold the interval ID outside of React state to guarantee cleanup ordering.

---

**[FD-010] `useBootstrap` missing dependency declarations**

- File: `frontend/src/core/hooks/useBootstrap.ts:48`
- Problem: `useEffect(() => {...}, [])` uses `setToken`, `setUser`, `setSetupComplete`, `setInitialised` from the outer scope but does not list them in deps. The `hasRun.current` guard prevents actual re-runs, but the pattern is fragile.
- Fix: Add the setters to the dependency array (they are stable Zustand selectors), or replace the `hasRun` pattern with a proper once-only pattern.

---

#### Medium Effort

**[FD-011] `EditTab.tsx` model capability check does not re-run when persona changes**

- File: `frontend/src/app/components/persona-overlay/EditTab.tsx:48-66`
- Problem: The `useEffect` that loads model capabilities has an empty deps array with eslint-disable. If the `PersonaOverlay` is navigated from one persona to another without unmounting, the displayed capabilities remain from the previous persona.
- Fix: Add `persona.model_unique_id` to the dependency array and remove the eslint-disable comment.

---

**[FD-012] `ChatView.tsx` optimistic message uses non-unique `Date.now()` ID**

- File: `frontend/src/features/chat/ChatView.tsx:229`
- Problem: Each optimistic user message gets a timestamp-based ID. Two messages sent within the same millisecond produce duplicate IDs, causing React key collisions.
- Fix: Use `crypto.randomUUID()` instead of `Date.now()` for optimistic IDs.

---

**[FD-013] `localIdCounter` in `useAttachments` is a module-level singleton**

- File: `frontend/src/features/chat/useAttachments.ts:6`
- Problem: `let localIdCounter = 0` is at module scope. It is never reset between sessions or chat navigations. If pending attachment state is ever persisted, stale IDs could collide.
- Fix: Move the counter inside the hook or use `crypto.randomUUID()`.

---

### Low Urgency

#### Low Effort

**[FD-014] `HistoryItem.tsx` date locale is hard-coded to `de-DE`**

- File: `frontend/src/app/components/sidebar/HistoryItem.tsx:7`
- Problem: `toLocaleDateString("de-DE", ...)` hard-codes German locale formatting for all users. Similarly in `frontend/src/app/components/persona-overlay/HistoryTab.tsx:41`.
- Fix: Use `undefined` (system locale) or `navigator.language` instead of `"de-DE"`.

---

**[FD-015] `BookmarkModal` does not restore focus on close**

- File: `frontend/src/features/chat/BookmarkModal.tsx`
- Problem: `UserModal` and `PersonaOverlay` both save `document.activeElement` and restore focus on cleanup. `BookmarkModal` does not.
- Fix: Add focus save/restore in the cleanup of the Escape key effect.

---

**[FD-016] `Sidebar.tsx` uses inline async handlers with no error rollback for toggle-pin/session-pin**

- File: `frontend/src/app/layouts/AppLayout.tsx:181-184`
- Problem: The `onToggleSessionPin` handler calls `updateChatSession` (optimistic) then the API in a fire-and-forget fashion. If the API call fails, the optimistic update is never rolled back.
- Fix: Either roll back the optimistic update on error, or make the button disabled while the request is in flight.

---

#### Medium Effort

**[FD-017] `useEnrichedModels` does not react to LLM events -- stale after curation changes**

- File: `frontend/src/core/hooks/useEnrichedModels.ts`
- Problem: Unlike `useLlm`, `useEnrichedModels` has no WebSocket event subscriptions. Model browser shows stale curation ratings until the user closes and reopens the modal.
- Fix: Subscribe to `LLM_MODEL_CURATED`, `LLM_MODELS_REFRESHED`, and `LLM_USER_MODEL_CONFIG_UPDATED` events and call `refetch`.

---

**[FD-018] `Topbar` model display strips only the first segment when splitting on `:`**

- File: `frontend/src/app/components/topbar/Topbar.tsx:109`
- Problem: `.split(":")[1]` only takes the second segment. For compound model slugs (e.g. `ollama_cloud:qwen2.5:72b`), this shows only `qwen2.5` instead of `qwen2.5:72b`.
- Fix: Use `.split(":").slice(1).join(":")` -- as already done correctly in `EditTab.tsx:32-33`.

---

#### High Effort

**[FD-019] `chatStore` is a single global singleton -- second open ChatView tab corrupts state**

- File: `frontend/src/core/store/chatStore.ts`
- Problem: `useChatStore` is a module-level Zustand singleton with no session scoping. If a user opens two browser tabs both pointing to different chat sessions, they share one global `useChatStore`. `reset()` runs on every session navigation and clears all chat state globally, including the other tab.
- Why it matters: Multi-tab usage (documented as supported: "Multiple concurrent sessions per user are supported") will corrupt chat state.
- Fix: Either scope the store by `sessionId` or use `useReducer` local to `ChatView` for session-specific streaming state.

---

### Low Urgency

#### Low Effort

**[FD-020] `useAuth.login` calls `connect()` redundantly -- `useWebSocket` already reacts to `isAuthenticated`**

- File: `frontend/src/core/hooks/useAuth.ts:30`
- Problem: After a successful login, `useAuth.login` explicitly calls `connect()`. Simultaneously, `setToken()` sets `isAuthenticated: true`, which triggers `useWebSocket`'s effect (which also calls `connect()`). Causes unnecessary socket churn on every login.
- Fix: Remove the explicit `connect()` call from `useAuth.login`.

---

**[FD-021] `useAuth.changePassword` calls `disconnect()`/`connect()` duplicating `useWebSocket` logic**

- File: `frontend/src/core/hooks/useAuth.ts:63-64`
- Problem: Same pattern as above. The token change via `setToken` will trigger `useWebSocket`'s effect anyway.
- Fix: Remove the manual `disconnect()`/`connect()` calls from `changePassword`.

---

**[FD-022] `displaySettingsStore` calls `localStorage.getItem` during module initialisation**

- File: `frontend/src/core/store/displaySettingsStore.ts:11,53`
- Problem: `localStorage` access runs synchronously when the module is first imported. In SSR or test environments without a DOM, `localStorage` is undefined. Same issue in `sanitisedModeStore.ts:10` and `sidebarStore.ts:10`.
- Fix: Add `typeof localStorage !== 'undefined'` guard, or use Zustand's `persist` middleware.

---

#### Medium Effort

**[FD-023] `useBookmarks` double-fetch pattern: initial fetch + event-driven insert**

- File: `frontend/src/core/hooks/useBookmarks.ts:32`
- Problem: The deduplication guard is correct, but two insertion paths (REST response in `ChatView.tsx` and event handler) exist. The `addBookmark` call in `ChatView.tsx` is architecturally redundant -- it exists because the REST call returns the DTO before the event arrives. Design smell that should be documented or simplified.
- Fix: Document the intent explicitly with a comment, or if the bookmark event is sufficiently reliable, remove the `addBookmark` call and rely entirely on the event.

---

#### High Effort

**[FD-024] `chatStore` `finishStreaming` -- `useChatStream.ts:84` uses `setState` directly bypassing store setters**

- File: `frontend/src/core/store/chatStore.ts:99-105`
- Problem: `useChatStream.ts:84` calls `useChatStore.setState({ contextStatus, contextFillPercentage })` directly, bypassing the store's setter functions -- an internal encapsulation violation.
- Fix: Use the store's `setContextStatus`/`setContextFillPercentage` setters rather than `setState` directly, or add those setters to the store.

---

## 2. Requires Backend Coordination

---

### Critical / High Urgency

#### Low Effort

**[FD-025] `CHAT_STREAM_ENDED` event must include the real server-assigned message ID**

- Files: `frontend/src/features/chat/useChatStream.ts:66`, backend `chat` module
- Problem: The frontend constructs the final assistant message with a fake ID (see FD-002). The backend has already persisted the message with a real MongoDB ObjectId. The `CHAT_STREAM_ENDED` event payload needs to include `message_id`.
- Fix: Backend: include `message_id` in the `CHAT_STREAM_ENDED` payload. Frontend: use `p.message_id` when constructing the final message DTO.

---

#### Medium Effort

**[FD-026] Avatar images served as authenticated resources require JWT in the URL -- token leakage risk**

- Files: `frontend/src/core/api/personas.ts:70-75`, `frontend/src/core/api/storage.ts:81`
- Problem: `avatarSrc` appends the JWT access token as a query parameter. This is necessary because `<img src>` cannot send custom headers. However, JWTs in URLs appear in server access logs, browser history, and HTTP referrer headers.
- Fix (backend): Implement short-lived single-use signed URLs for avatar downloads. Fix (frontend): Update `avatarSrc` and `storageApi.downloadUrl` to use them.

---

### Medium Urgency

#### Low Effort

**[FD-027] `usePersonas` event payload is not used -- events from other users are ignored**

- File: `frontend/src/core/hooks/usePersonas.ts:29-31`
- The backend already sends the persona DTO in persona events per the event-first architecture. The frontend simply does not use it. Both a frontend fix (use the payload) and a verification that the backend payload structure matches `PersonaDto`.

---

#### Medium Effort

**[FD-028] Token refresh race: `handleTokenRefresh` can fire twice simultaneously**

- File: `frontend/src/core/websocket/connection.ts:128-139`
- Problem: `handleTokenRefresh` is called from two separate paths: (1) `socket.onmessage` when `type === "token.expiring_soon"`, and (2) `socket.onclose` when `ev.code === 4001`. Both calls hit `authApi.refresh()` concurrently, potentially resulting in two new tokens.
- Fix (frontend): Add an `isRefreshing` flag to prevent concurrent calls. Fix (backend): Ensure refresh tokens remain valid for a short grace period after first use.

---

### Low Urgency

#### Low Effort

**[FD-029] `bookmarksApi.list` does not URL-encode the `session_id` parameter**

- File: `frontend/src/core/api/bookmarks.ts:9`
- Problem: The query string does not URL-encode `sessionId`. MongoDB ObjectIds are alphanumeric so this is not currently exploitable, but it is inconsistent.
- Fix: Use `new URLSearchParams({ session_id: sessionId }).toString()`.
