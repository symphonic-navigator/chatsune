# Project Brief — Voice Commands, Part 2: System Voice + Cache

**Date:** 2026-04-30
**Status:** Brief, not yet a full spec. Run a brainstorming session to expand into one.
**Predecessor:** `2026-04-30-voice-commands-foundation-design.md` (Part 1, foundation)
**Successor (blocked on this):** Companion commands (Part 3)

---

## Context

Part 1 ships the voice-command foundation: registry, normaliser, matcher, dispatcher, plugin-lifecycle integration, one built-in `debug` command. Command responses today flow through `frontend/src/features/voice-commands/responseChannel.ts`, which renders `displayText` as a toast and ignores `spokenText`.

Part 2 swaps the body of `respondToUser` to play `spokenText` through a user-configured system voice, with the toast path preserved as a fallback when no system voice is configured. Command-handler code does not change.

## Goals

1. **System-voice selection** — let the user pick which TTS voice (engine + voice ID) speaks command responses. Lives somewhere sensible in the existing settings UI; a new card in `VoiceTab.tsx` is the obvious home.
2. **Cache layer** — keyed on `(voiceId, spokenText)`. Cache hits skip TTS synthesis entirely. Bound the cache (size or count); decide TTL or pure LRU.
3. **TTS-pipeline reuse** — call into the existing voice engine adapters in `frontend/src/features/voice/engines/`; do **not** spin up a parallel synth path.
4. **Dedicated audio channel** — system-voice playback overlays the persona (does not block her, does not pause her, is not pausable by barge). Conceptually a second small audio context / element separate from the existing speech-segment queue.
5. **Toast fallback** — when no system voice is configured, fall back to the same `useNotificationStore` path the foundation uses today. This is also the failure mode if synthesis throws.
6. **Cache observability** — `console.debug` lines on cache hit/miss so debugging is straightforward.

## Non-goals

- Companion commands themselves — Part 3.
- Hue, Lovense, or any other integration commands — owned by the integration plugin.
- New trigger words, new normalisation rules, new dispatcher behaviour — interface stays as Part 1 defined it.
- Backend-side synthesis or backend-side caching — the cache lives in the browser, scoped to the user's session. Persistence across sessions is open and worth deciding during brainstorming (IndexedDB blob cache is a candidate).
- Multi-voice routing per command (e.g. "errors in voice A, success in voice B") — single voice for all command responses.

## Open design questions to resolve in brainstorming

- **Cache persistence:** in-memory only (lost on refresh) vs IndexedDB (persists, survives reloads, eats disk).
- **Cache eviction:** size-bounded LRU, count-bounded LRU, or TTL-based.
- **Voice engine choice:** all engines that support `synthesise(text, voiceId) → audio`, or restricted to a curated subset (e.g. exclude expensive cloud engines from being used for one-line confirmations).
- **Audio channel implementation:** a separate `<audio>` element, a separate Web Audio `AudioBufferSourceNode`, or reuse the existing playback infrastructure with a "system" priority lane.
- **What if the user is currently speaking?** Probably play anyway — it is a confirmation, not a competing prompt. But worth confirming.
- **What if the persona is mid-sentence and the system voice plays over her?** Either accept the overlap (matches the "system voice is its own channel" framing) or duck the persona briefly. Pick one.
- **Default volume / mixing:** does system voice get its own volume control or share the persona's?

## Touch surface

- **Modify:** `frontend/src/features/voice-commands/responseChannel.ts` — replace function body, keep signature.
- **Modify:** `frontend/src/features/voice/engines/` — likely no change, just consumed.
- **Add:** a small cache module under `frontend/src/features/voice-commands/` (e.g. `responseCache.ts`).
- **Add:** a small audio playback module under `frontend/src/features/voice-commands/` (e.g. `responsePlayer.ts`).
- **Modify:** `frontend/src/app/components/user-modal/VoiceTab.tsx` (or the right settings location) — add the system-voice picker card.
- **Modify:** user settings store / API — persist the chosen system voice.

## Success criteria

- A test user enables continuous voice, says `"debug hello"`, hears the configured system voice speak `"Debug command received."`, and still sees the toast (toast stays in v2 — visual confirmation is cheap and useful).
- Saying `"debug hello"` again uses the cache: no synthesis call observable, audio plays immediately.
- Switching the system voice in settings invalidates the cache for the old voice (or simply lets old entries age out — decide during brainstorming).
- Clearing the system-voice setting reverts to toast-only without any other code change.
- Companion commands (Part 3) can be implemented without revisiting Part 2 code.
