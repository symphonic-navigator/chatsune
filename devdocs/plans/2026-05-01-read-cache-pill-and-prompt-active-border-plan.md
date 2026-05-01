# Read Cache Pill and Prompt Active Border — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two small UX-polish features. (A) The Read button shows a desaturated-green colour when the message is cached for the active voice. (B) The prompt input pulses a gold border while the LLM is producing a response (excluding TTS playback).

**Architecture:** Both items are frontend-only. Item A adds a tiny listener pattern to the existing module-scope LRU so React components can react to cache mutations without a full Zustand refactor. Item B adds one CSS keyframe and a derived boolean trigger on the textarea.

**Tech Stack:** React + TSX, Tailwind CSS, vanilla CSS keyframes. No new dependencies.

---

## File Structure

### Item A — Read cache pill

- **Modify** `frontend/src/features/voice/components/ReadAloudButton.tsx`:
  - Add a `cacheListeners` Set + a `notifyCacheListeners()` helper next to the existing `cacheGet`/`cachePut`.
  - Add a `useCacheTick()` hook that subscribes/unsubscribes a listener and returns an incrementing tick number.
  - Wire `cachePut` (and the cache-eviction step inside it) to call `notifyCacheListeners()`.
  - In the `ReadAloudButton` component, derive `isCached` via `useMemo` and apply the green-idle colour classes when `isCached && !isActive`.

### Item B — Prompt active border

- **Modify** `frontend/src/index.css`:
  - Add `@keyframes promptActive`, the `.prompt-active-border` class, and a `prefers-reduced-motion` override.
- **Modify** `frontend/src/features/chat/ChatInput.tsx`:
  - Import `useChatStore` (for `isStreaming`), `useVoicePipelineStore` (for `state.phase`), and `usePhase` (for the conversation-mode phase).
  - Derive `isResponseActive`.
  - Add the `prompt-active-border` class to the textarea conditionally.

No new files. No backend changes. No store-shape changes.

---

## Task 1: Read cache pill (Item A)

**Files:**
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Add cache reactivity helpers next to the existing cache**

Open `frontend/src/features/voice/components/ReadAloudButton.tsx`. Find the cache section (around lines 88-110) which currently looks like:

```typescript
// ── LRU cache ──

interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

function cacheGet(key: string): CachedAudio | undefined {
  const entry = cache.get(key)
  if (entry) { cache.delete(key); cache.set(key, entry) }
  return entry
}

function cachePut(key: string, entry: CachedAudio): void {
  cache.delete(key)
  cache.set(key, entry)
  if (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
}
```

Replace it with:

```typescript
// ── LRU cache ──

interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

// Listeners called whenever the cache mutates (insert or evict). Used by
// ReadAloudButton instances so the green "cached" pill reacts to cache
// changes without turning the cache itself into a Zustand store.
const cacheListeners = new Set<() => void>()

function notifyCacheListeners(): void {
  for (const listener of cacheListeners) listener()
}

function cacheGet(key: string): CachedAudio | undefined {
  const entry = cache.get(key)
  if (entry) { cache.delete(key); cache.set(key, entry) }
  return entry
}

function cachePut(key: string, entry: CachedAudio): void {
  cache.delete(key)
  cache.set(key, entry)
  if (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
  notifyCacheListeners()
}

// React hook: returns a number that increments on every cache mutation.
// Components depend on this in useMemo deps to re-evaluate cache-hit
// derivations when the cache changes.
function useCacheTick(): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const listener = () => setTick((t) => t + 1)
    cacheListeners.add(listener)
    return () => {
      cacheListeners.delete(listener)
    }
  }, [])
  return tick
}
```

The `useState` and `useEffect` imports are already present at the top of the file — no import changes needed for this hook.

- [ ] **Step 2: Derive `isCached` in the component**

Inside `ReadAloudButton`, after the existing voice resolution block (the lines that compute `voiceId`, `narratorVoiceId`, `resolvedMode` — around line 258-260), add:

```typescript
const cacheTick = useCacheTick()
const isCached = useMemo(() => {
  if (!voiceId) return false
  const key = readAloudCacheKey(messageId, voiceId, narratorVoiceId, resolvedMode)
  return cacheGet(key) !== undefined
  // cacheTick is intentionally a dep but not used: it forces re-evaluation
  // when the cache mutates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [messageId, voiceId, narratorVoiceId, resolvedMode, cacheTick])
```

If `useMemo` is not yet imported in the file, add it to the existing React import (which already has `useCallback`).

- [ ] **Step 3: Apply the green idle styling when cached**

Find the JSX where the button's text-colour class is set (around line 350 per earlier mapping — look for `text-white/25 hover:text-white/50` in a className expression). The current state-driven colour selection looks roughly like this:

```tsx
className={cx(
  // ...other classes...
  isActive && state !== 'idle' ? 'text-gold' : 'text-white/25 hover:text-white/50',
)}
```

(The exact form may differ slightly — find the corresponding ternary or conditional-class block.)

Replace the colour selection so that the cached-idle case uses emerald:

```tsx
className={cx(
  // ...other classes...
  isActive && state !== 'idle'
    ? 'text-gold'
    : isCached
      ? 'text-emerald-400/45 hover:text-emerald-400/65'
      : 'text-white/25 hover:text-white/50',
)}
```

The icon inside the button inherits `currentColor` already (verify quickly: the SVG `stroke` or `fill` should reference `currentColor`, not a hard-coded colour). If the icon does NOT inherit `currentColor`, also colour-swap the icon. From the prior mapping the speaker icon does inherit `currentColor`; if you find otherwise, STOP and report so the spec can be revisited.

- [ ] **Step 4: Build and verify**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build (`tsc -b` and Vite). If TypeScript flags `useMemo` or `useState` as unused (because you imported but didn't use one), trim the import.

- [ ] **Step 5: Quick visual smoke test (dev server, no manual verification yet)**

Verify the dev server is running (`pnpm run dev` in `frontend/`). Open a chat with at least one assistant message. Confirm:
- The Read button on each message renders without a runtime error.
- The button's idle colour is the existing white/25 (no message has been read yet, cache is empty).

Do NOT do the full manual verification yet — that happens after Task 2 is done so both items can be exercised together.

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/components/ReadAloudButton.tsx
git commit -m "Add cached-state green pill to Read button"
```

---

## Task 2: Prompt active border (Item B)

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/features/chat/ChatInput.tsx`

- [ ] **Step 1: Add the keyframe and class to index.css**

Open `frontend/src/index.css`. The existing keyframes (`messageEntrance`, `thinkPulse`, `toastEnter`, `toastExit`) live around lines 83-179. After the last existing `@keyframes` block (and any related class definitions), add:

```css
@keyframes promptActive {
  0%, 100% {
    border-color: rgba(201, 168, 76, 0.25);
    box-shadow: 0 0 0 1px rgba(201, 168, 76, 0.10);
  }
  50% {
    border-color: rgba(201, 168, 76, 0.55);
    box-shadow: 0 0 12px rgba(201, 168, 76, 0.20);
  }
}

.prompt-active-border {
  animation: promptActive 2.4s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .prompt-active-border {
    animation: none;
    border-color: rgba(201, 168, 76, 0.45);
    box-shadow: 0 0 0 1px rgba(201, 168, 76, 0.15);
  }
}
```

The hex `#c9a84c` (RGB `201, 168, 76`) is the existing app gold (defined elsewhere in `index.css` as `--color-gold`). Using literal RGB rather than `var(--color-gold)` here keeps the keyframe self-contained and avoids any risk of the variable being overridden in scope.

- [ ] **Step 2: Add the imports to ChatInput.tsx**

Open `frontend/src/features/chat/ChatInput.tsx`. The current imports at the top of the file include `useViewport`, `hapticTap`, etc. Add:

```typescript
import { useChatStore } from '../../core/store/chatStore'
import { useVoicePipelineStore } from '../voice/stores/voicePipelineStore'
import { usePhase } from '../voice/hooks/usePhase'
```

If any of those import paths differ in this codebase (e.g. `usePhase` lives in a different folder), find the actual path with:

```bash
rg -ln "export (function|const) usePhase" frontend/src
rg -ln "export (function|const) useChatStore" frontend/src
rg -ln "export (function|const) useVoicePipelineStore" frontend/src
```

Adjust the import paths to match. If `usePhase` does not exist as a named hook (the prior mapping says it does, but verify), STOP and report — the trigger logic depends on it.

- [ ] **Step 3: Derive `isResponseActive`**

Inside the `ChatInput` component body, near the top with the other hook calls (after the existing `useState`/`useRef` calls, before the JSX), add:

```typescript
const isStreaming = useChatStore((s) => s.isStreaming)
const readAloudPhase = useVoicePipelineStore((s) => s.state.phase)
const conversationPhase = usePhase()

const isResponseActive =
  isStreaming &&
  readAloudPhase !== 'speaking' &&
  conversationPhase !== 'speaking'
```

If `usePhase()` returns an object rather than a string (the prior mapping suggested it returns a `ConversationPhase` directly, but the codebase may wrap it), check by typing the inference: hover or `rg` the function signature. Adjust the comparison to match (`conversationPhase.phase !== 'speaking'` etc.). The exact name `'speaking'` is from the prior mapping; if the actual type uses a different literal (e.g. `'tts'` or `'playback'`), use whichever literal corresponds to "TTS audio is currently playing back".

- [ ] **Step 4: Apply the conditional class to the textarea**

Find the textarea element (around lines 209-220 per the prior mapping). Its current `className` is a string of Tailwind classes:

```tsx
<textarea
  ref={textareaRef}
  className="chat-text block max-h-[40vh] w-full resize-none overflow-y-auto rounded-lg border border-white/8 bg-white/4 px-3 py-2 pr-10 text-white/90 placeholder-white/55 outline-none transition-colors focus:border-white/15 focus:bg-white/6 disabled:opacity-40 lg:max-h-none lg:overflow-hidden"
  ...
/>
```

Convert the className to a conditional join. Use template literals or a `cx`/`clsx` helper if the file already imports one — check first:

```bash
rg -n "from 'clsx'|from 'classnames'|^const cx" frontend/src/features/chat/ChatInput.tsx
```

If a helper is in use, follow the existing pattern. If not, use a template literal:

```tsx
<textarea
  ref={textareaRef}
  className={`chat-text block max-h-[40vh] w-full resize-none overflow-y-auto rounded-lg border border-white/8 bg-white/4 px-3 py-2 pr-10 text-white/90 placeholder-white/55 outline-none transition-colors focus:border-white/15 focus:bg-white/6 disabled:opacity-40 lg:max-h-none lg:overflow-hidden${
    isResponseActive ? ' prompt-active-border' : ''
  }`}
  ...
/>
```

Do NOT remove the existing `border border-white/8` and `focus:border-white/15` classes — they remain the static styling. The keyframe overrides the `border-color` only while the animation is running; when the trigger flips off, the static border returns naturally.

- [ ] **Step 5: Build and verify**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build. If a TypeScript error mentions an unknown property on the store selector (e.g. `s.isStreaming` not on the `chatStore` shape), check the store's type definition and adjust the selector. If `s.state.phase` does not match the actual `voicePipelineStore` shape, locate the correct selector — the previous mapping called it `useVoicePipelineStore((s) => s.state)` and `state.phase`, so a selector that only picks the phase is fine.

- [ ] **Step 6: Manual verification (covers both Task 1 and Task 2)**

The product owner runs these against the dev server (`pnpm run dev` in `frontend/`).

**Item A — Read cache pill:**

1. Open a chat with at least three assistant messages.
2. Click "Read" on message X. Wait for playback to start, then for it to finish (or stop manually). The button returns to idle.
3. **Expected:** the button on message X is desaturated green (text + speaker icon both green); other buttons are still white.
4. Switch the persona's TTS voice (or change the voice in integration settings) so the cache key changes for message X.
5. **Expected:** the green pill on message X reverts to white.
6. Switch back to the original voice.
7. **Expected:** the green pill returns.
8. Reload the page.
9. **Expected:** all buttons are white again (cache is in-memory).

**Item B — Prompt active border:**

10. **Text-only chat — animation appears.** Submit a prompt in a chat without TTS. Observe the prompt input border: it begins pulsing gold within ~50 ms of submit and continues for the duration of the response. When the response finishes, the border returns to its static state.
11. **Read-aloud — animation does NOT appear.** With response done, click "Read" on a message. While the audio plays, the prompt input border stays static white.
12. **Continuous voice — animation does NOT appear during playback.** In continuous voice mode, send a voice message. While the LLM thinks and streams: pulse animates. When the assistant's reply starts speaking via TTS: animation stops.
13. **Reduced motion.** Toggle the OS-level reduced-motion setting. Submit a prompt. The border becomes a static gold during the response, no pulsing.

If any scenario fails, do NOT proceed with the commit — report the symptom (which scenario, what was observed, what was expected).

- [ ] **Step 7: Commit**

After manual verification passes:

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/index.css frontend/src/features/chat/ChatInput.tsx
git commit -m "Pulse prompt input border while response is in flight"
```

---

## Constraints for all tasks

- Do NOT merge to master, do NOT push, do NOT switch branches, do NOT amend prior commits.
- Do NOT add unit tests — both items are visual / behavioural and verified manually.
- Do NOT touch backend, store shapes, or any file outside the lists in each task.
- Do NOT change the existing `cacheGet`/`cachePut` semantics — only add the listener notification side-effect to `cachePut`.
- Frontend build check: `pnpm run build` (which runs `tsc -b`), not `pnpm tsc --noEmit`.
- All user-facing text stays as it is today (the cache pill is colour-only, no new label). All identifiers in British English.
