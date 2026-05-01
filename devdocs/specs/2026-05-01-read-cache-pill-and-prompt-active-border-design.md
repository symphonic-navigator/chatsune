# Read Cache Pill and Prompt Active Border

Two small UX-polish items bundled into one spec because they are
independent but ship together. Both are about giving the user more
"feel" for what the system is doing.

## Item A — Read button shows cache state

### Problem

The "Read" button on each assistant message synthesises TTS via the
configured voice integration and caches the result in a frontend LRU
(eight entries). When the user clicks "Read" a second time on the
same message with the same voice, playback is essentially instant.
But the user has no visual signal that the audio is cached — they
click and discover.

For users who lean on read-aloud (re-listening to longer
explanations), seeing "this one is instant" matters.

### Goal

A user can tell at a glance which messages have a cached read-aloud
under the currently selected voice.

### Design

Add a fourth visual state to `ReadAloudButton`:

| Button state | Colour | Label / icon |
|---|---|---|
| idle, not cached | `text-white/25` | "Read" + speaker icon (today) |
| idle, **cached** | `text-emerald-400/45` (desaturated green) | "Read" + speaker icon (today, just recoloured) |
| preparing | `text-gold` + spinner | "Preparing…" (today) |
| playing | `text-gold` + stop icon | "Stop" (today) |

Both the text and the icon turn green in the cached-idle state. Hover
brightens the green proportionally to how the white/25 hover lifts
today (so: `hover:text-emerald-400/65` or similar — keep the existing
hover ratio).

#### Cache-hit derivation

The cache is a module-scope `Map` in
`frontend/src/features/voice/components/ReadAloudButton.tsx`, keyed by
`readAloudCacheKey(messageId, primaryVoiceId, narratorVoiceId, mode)`.
The cache-hit check is O(1) and lives next to the cache module:

```ts
const isCached = useMemo(() => {
  if (!primaryVoice?.id) return false
  const key = readAloudCacheKey(messageId, primaryVoice.id, narratorVoice?.id, mode)
  return cacheGet(key) !== undefined
}, [messageId, primaryVoice?.id, narratorVoice?.id, mode, cacheTick])
```

`cacheTick` is a small reactivity helper: a `useCacheTick()` hook
returning a number that increments whenever the cache is mutated
(insert or evict). It lets the button's `useMemo` re-evaluate without
turning the cache itself into a Zustand store. Implementation: a
module-level `Set<() => void>` of listeners; `useCacheTick` subscribes
on mount and unsubscribes on unmount; cache-mutating helpers call all
listeners. This is small enough to live inline in the same module as
the cache.

Per-button reactivity is correct because the user only cares about
the button they're looking at:
- A button whose cache entry was just written re-renders (the playback
  state changes anyway, and `cacheTick` triggers a re-evaluation).
- Other buttons rendering the same message in the same voice would
  also pick up the change via `cacheTick` — relevant if the same
  message is rendered twice (rare, but free).
- Voice change re-resolves `primaryVoice.id` from the persona store,
  causing a fresh `useMemo` evaluation; the new key probably misses
  → button reverts to white. Correct.
- LRU eviction triggers `cacheTick`; affected buttons re-render and
  show the un-cached state. If the user clicks anyway, the synthesise
  path runs and re-caches. No bug.

#### Out of scope for Item A

- Persisting the cache to IndexedDB so it survives reloads. Today's
  semantics (in-memory, session-only) are accepted.
- Increasing `CACHE_MAX` from 8. Tunable later if real-world feedback
  asks for it.
- A "this is being synthesised right now in the background" state.
  Not a current need.

### Manual verification (Item A)

1. Open a chat with several assistant messages.
2. Click "Read" on message X. Wait for playback to start, then for
   it to finish (or stop manually). The button returns to idle.
3. **Expected:** the button on message X is now desaturated green
   ("Read" text + speaker icon both green), other buttons still
   white.
4. Switch the persona's TTS voice (or pick a different voice in
   integration settings) so the cache key changes.
5. **Expected:** the green pill on message X reverts to white,
   because the new voice's cache entry is missing.
6. Switch back to the original voice.
7. **Expected:** the green pill returns (the cache entry from step 2
   is still in the LRU).
8. Reload the page.
9. **Expected:** all buttons are white again (cache is in-memory and
   does not persist).

---

## Item B — Prompt input shows "something is happening"

### Problem

The chat prompt input is visually static. When the user submits a
message and the LLM is thinking and streaming tokens, the only signal
that work is in flight is the streaming text in the message list.
Tester feedback: people want to *feel* that the system is working,
not just see new tokens appear.

The prompt input is the obvious place — it's where the user's
attention rests right after submit, and it's the natural anchor for
"the system is responding to my last input".

### Goal

While the LLM is producing a response (inference + token streaming,
**not** during TTS playback of any kind), the prompt input has a
gentle pulsing gold border that signals "something is happening here".

### Design

#### Trigger

```ts
const isResponseActive = isStreaming
  && readAloudPhase !== "speaking"
  && conversationPhase !== "speaking"
```

- `isStreaming`: from `useChatStore((s) => s.isStreaming)` — true
  during ResponseTaskGroup states `before-first-delta`, `streaming`,
  `tailing`.
- `readAloudPhase`: from `useVoicePipelineStore((s) => s.state.phase)`
  — the read-aloud TTS pipeline phase. `"speaking"` means the user
  hit a Read button and audio is playing.
- `conversationPhase`: from `usePhase()` — the live-voice
  conversation phase. `"speaking"` means continuous voice mode is
  playing back the assistant's TTS.

The two playback exclusions are intentionally separate: one covers
read-aloud-from-history, the other covers live-voice-mode TTS.
Either turning `"speaking"` halts the animation.

If neither voice mode is active (text-only chat), both phases stay
non-`"speaking"` and the trigger collapses to just `isStreaming`.

#### Style

A new keyframe in `frontend/src/index.css`, alongside the existing
`thinkPulse` and `messageEntrance`:

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
```

Applied conditionally to the textarea:

```tsx
<textarea
  className={cx(
    "chat-text block max-h-[40vh] w-full resize-none ...",
    isResponseActive && "prompt-active-border",
  )}
  ...
/>
```

Notes:
- `2.4s` per full cycle: slow enough to read as "ambient", fast
  enough to feel alive. `thinkPulse` uses `2s`; this is in the same
  family.
- Gold (`#c9a84c`) matches the rest of the app's "active" accent
  (Read button playing, cockpit highlights, bookmark active).
- The animation overrides the textarea's existing
  `border border-white/8` and `focus:border-white/15` while active.
  When the trigger flips off, the regular border returns. The CSS
  cascade handles this naturally because the keyframe sets
  `border-color` directly; on stop, the static border-color from the
  Tailwind utility takes over.
- The textarea's `outline-none` and other Tailwind classes stay
  unchanged. We only swap the border treatment.

#### Reduced motion

Honour `@media (prefers-reduced-motion: reduce)` by disabling the
animation in `index.css`:

```css
@media (prefers-reduced-motion: reduce) {
  .prompt-active-border {
    animation: none;
    border-color: rgba(201, 168, 76, 0.45);
    box-shadow: 0 0 0 1px rgba(201, 168, 76, 0.15);
  }
}
```

Reduced-motion users still get a visual signal — a static gold border
— so the "something is happening" affordance isn't lost; it just
isn't moving.

#### Out of scope for Item B

- Animating the submit button or the surrounding container.
- A different colour or animation per phase (thinking vs. streaming).
  YAGNI — one signal is enough.
- Animation while the user is typing into the input. The animation
  is response-driven, not user-input-driven.

### Manual verification (Item B)

1. **Text-only chat — animation appears.** Submit a message in a
   chat that does not use TTS. Observe the prompt input border:
   it begins pulsing gold within ~50 ms of submit and continues for
   the duration of the response (thinking + streaming). When the
   response finishes, the border returns to its static state.
2. **Read-aloud — animation does NOT appear.** With response done
   (border idle), click "Read" on a message. While the audio plays,
   the prompt input border stays static white.
3. **Continuous voice — animation does NOT appear during playback.**
   In continuous voice mode, send a voice message. While the LLM
   thinks and streams: pulse animates. When the assistant's reply
   starts speaking via TTS: animation stops, border static. When
   speaking finishes and the next listening cycle begins:
   animation stays static (idle).
4. **Combined — read-aloud during a streaming response.** This
   shouldn't normally happen (Read is for finished messages), but
   if a Read playback is active and the user submits a new prompt
   that starts streaming, the animation should NOT run (playback
   exclusion still applies). When playback stops, animation
   resumes if `isStreaming` is still true.
5. **Reduced motion.** Toggle the OS-level reduced-motion setting
   on. Submit a prompt. The border becomes a static gold during the
   response, no pulsing.

---

## Files affected

- `frontend/src/features/voice/components/ReadAloudButton.tsx`
  — add `isCached` derivation and the green-idle styling. Add the
  `useCacheTick` listener helper alongside the existing cache (or
  in a sibling file in the same folder if it's clearer).
- `frontend/src/features/chat/ChatInput.tsx` — add the
  `isResponseActive` derivation and the conditional class on the
  textarea. Wire `useVoicePipelineStore` and `usePhase()` if not
  already imported.
- `frontend/src/index.css` — add `@keyframes promptActive`, the
  `.prompt-active-border` class, and the reduced-motion override.

No backend changes. No store-shape changes. No new files needed
(the cache-tick helper can live inside `ReadAloudButton.tsx` or in
the existing `pipeline/` folder next to `readAloudCacheKey.ts`).
