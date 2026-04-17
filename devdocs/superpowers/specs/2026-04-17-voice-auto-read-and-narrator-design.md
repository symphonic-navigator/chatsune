# Voice Auto-Read Indicator & Narrator Mode

Date: 2026-04-17
Status: Design

## Summary

Polish the existing Mistral-backed voice integration by closing four gaps
discovered during first-run testing:

1. Fix the missing visual indicator on `ReadAloudButton` during auto-read.
2. Allow the user to abort an in-flight auto-read (synthesis or playback).
3. Invalidate the read-aloud cache when the selected voice changes.
4. Introduce a narrator mode with a separately selectable narrator voice.

A follow-up spec will cover sentence-by-sentence streaming with an
inter-sentence pause control. This spec intentionally does not touch the
`AudioPlaybackImpl` queue semantics.

## Motivation

The voice integration works end-to-end but has three usability bugs:

- Auto-read runs silently — no spinner, no stop-icon — because
  `triggerReadAloud()` updates the global `activeMessageId` but not the
  per-button `localState`.
- There is no gesture to stop auto-read once it is running.
- The LRU cache key is `messageId` only, so changing the persona voice still
  serves the previous audio.

The narrator feature is a separate user request with two flavours:

- **Roleplay mode** (SillyTavern-style): `*action*` is read by the
  narrator, everything else by the persona.
- **Narrated mode**: `"speech"` is read by the persona, everything else —
  prose and `*action*` blocks — by the narrator.

Both modes require a second voice. "Inherit from primary voice" is the
default.

## Non-Goals

- Sentence-by-sentence TTS streaming — separate spec.
- Inter-sentence pause control — separate spec.
- Changes to `AudioPlaybackImpl` queue semantics.
- Removing the unused Kokoro-era `voice_config.dialogue_voice` and
  `voice_config.narrator_voice` fields — tracked separately.

## Design

### A. Persona-config schema

- `voice_config.roleplay_mode: bool` is replaced by
  `voice_config.narrator_mode: Literal['off', 'play', 'narrate']`,
  default `'off'`.
- A Pydantic `@model_validator(mode='before')` translates legacy documents
  on read: `roleplay_mode: True` → `narrator_mode: 'play'`,
  `roleplay_mode: False` → `narrator_mode: 'off'`. The legacy key is
  dropped from the output. Since `voice_config` has not yet reached
  deployed users, no one-shot migration is required; the validator is
  sufficient for the local dev fixtures we have.
- The narrator voice id lives on the TTS integration's persona-scoped
  config, parallel to the existing primary voice:
  `persona.integration_configs[<tts_plugin_id>].narrator_voice_id`.
  A value of `null` signals "inherit from primary voice".
- Kokoro-era legacy fields (`voice_config.dialogue_voice`,
  `voice_config.narrator_voice`) remain as-is; their removal is out of
  scope here.

### B. Parser

`parseForSpeech(text: string, roleplay: boolean)` becomes
`parseForSpeech(text: string, mode: 'off' | 'play' | 'narrate')`:

- `off` → a single `{ type: 'voice', text }` segment (current behaviour).
- `play` → existing `parseRoleplay` logic.
- `narrate` → new logic:
  - Text inside `"..."` / `\u201c...\u201d` → `voice` segments.
  - Everything outside (including `*action*` blocks) → `narration`
    segments.

New cases in `audioParser.test.ts` cover all three modes plus edge cases
(empty string, mixed delimiters, nested markdown, trailing fragments).

### C. Active-reader state centralisation

The current design keeps a global `activeMessageId` plus a per-button
`localState`. Auto-read writes only the former, which is why the button
stays idle-looking. Replace with a single global tuple:

```ts
type ReadState = 'idle' | 'synthesising' | 'playing'

let activeMessageId: string | null = null
let activeState: ReadState = 'idle'

export function setActiveReader(id: string | null, state: ReadState): void
export function useActiveReader(messageId: string): { isActive: boolean; state: ReadState }
```

Both `ReadAloudButton.handleClick` and `triggerReadAloud` drive this state
through the same entry points. The button renders purely from
`useActiveReader`; no more per-button `localState`.

Consequences:

- Auto-read shows the same spinner → stop-icon progression as a manual
  click, because both paths call `setActiveReader(id, 'synthesising')`
  before synthesis and `setActiveReader(id, 'playing')` in
  `onSegmentStart`.
- Clicking the button during auto-read triggers the existing stop branch
  because `isActive && state !== 'idle'` is true.
- On error, both paths call `setActiveReader(null, 'idle')` — a single
  consistent reset.

### D. Read-aloud cache

Inline key construction is replaced by a helper:

```ts
function readAloudCacheKey(
  messageId: string,
  primaryVoiceId: string,
  narratorVoiceId: string | null,
  mode: NarratorMode,
): string {
  return `${messageId}:${primaryVoiceId}:${narratorVoiceId ?? '-'}:${mode}`
}
```

Invalidation is implicit: a new key is a cache miss, so changing voice,
narrator voice, or mode re-synthesises. Old entries fall out of the LRU
(cap of 8) naturally.

### E. `ReadAloudButton` voice resolution

- Primary voice: `persona.integration_configs[ttsId].voice_id` (unchanged).
- Narrator voice:
  `persona.integration_configs[ttsId].narrator_voice_id ?? primary`.
  A `null` narrator id means inherit — single-voice playback for that
  persona.
- Segment routing: `segment.type === 'voice'` → primary,
  `segment.type === 'narration'` → narrator.

The legacy `dialogueVoice` / `narratorVoice` props on the component stay
for test wiring but are deprecated; the production path is always
persona-driven.

### F. `PersonaVoiceConfig` UI

- Replace the "Roleplay Mode" toggle with a **Mode dropdown**:
  - *Off* — single voice, no segmentation.
  - *Roleplay (dialogue spoken)* — persona speaks dialogue, narrator
    speaks actions.
  - *Narrated (narration spoken)* — narrator speaks prose and actions,
    persona speaks dialogue only.
- Reveal a **Narrator Voice** dropdown when mode ≠ Off. First option:
  `{ value: null, label: 'Inherit from primary voice' }`.
- Add a small preview button next to the primary and narrator voice
  dropdowns. Clicking it synthesises a fixed test phrase with the
  currently selected voice via `ttsRegistry.active().synthesise()` and
  plays it through `audioPlayback`. The test phrase is
  `"The quick brown fox jumps over the lazy dog."`.
- Preview playback calls `audioPlayback.stopAll()` first, which
  interrupts any ongoing read-aloud or prior preview. Previews do not
  participate in `activeMessageId` tracking — they are not tied to a
  message and therefore never flip a `ReadAloudButton` into the active
  state. A `ReadAloudButton` click during preview still calls
  `audioPlayback.stopAll()` through its own path, cancelling the preview.

Styling matches the existing Mode/Auto-Read toggles — same label
typography, same chakra-coloured accents.

### G. TTS plugin (`mistral_voice`) config fields

Extend the plugin's `persona_config_fields` list with a
`narrator_voice_id` field:

- Same `optionsProvider` as `voice_id` (refreshes against the cloned-voice
  list).
- Prepend a synthetic first option
  `{ value: null, label: 'Inherit from primary voice' }` inside the
  plugin's `getPersonaConfigOptions('narrator_voice_id')` implementation,
  so the form layer stays unaware of the inherit semantics.
- Default value: `null`.

If the current `persona_config_fields` pipeline turns out to assume a
single voice field, the refactor to support two is in scope for this
spec. The risk is small — `GenericConfigForm` already iterates a field
array — but it is called out so it does not become a surprise.

## Testing

### Automated

- `audioParser.test.ts` — new cases for `off` / `play` / `narrate` modes,
  covering empty strings, mixed `"..."` and `*...*` delimiters, nested
  markdown, and trailing fragments.

### Manual

- Auto-read: stream a reply with auto-read on; button shows
  spinner → stop-icon progression; stop-icon click cancels playback.
- Stop during synthesis: click stop-icon while auto-read is still
  synthesising; synthesis loop aborts via the existing
  `activeMessageId !== messageId` guard.
- Voice change: read a message once so it is cached, change the
  persona's primary voice, click read again on the same message; a
  cache miss occurs and new audio is produced.
- Roleplay mode: message with mixed `"dialogue"` and `*action*` content
  plays with two distinct voices; narrator `null` inherits.
- Narrated mode: same message — voice roles are inverted; `*action*`
  goes to narrator.
- Preview buttons: each dropdown's preview plays the test phrase in the
  chosen voice without affecting any `ReadAloudButton` state; previews
  interrupt each other.
- Legacy document load: a persona record with `roleplay_mode: true`
  deserialises as `narrator_mode: 'play'` without error (local dev
  fixture).

## Risks

- **Plugin field pipeline**: adding a second voice field depends on
  `persona_config_fields` + `GenericConfigForm` handling two
  options-backed fields correctly. Low risk, called out above.
- **Preview independence**: previews bypass `activeMessageId`, which is
  a small special case in the otherwise single-reader model. The two
  cross-cancel only through `audioPlayback.stopAll()`. Mitigated by
  always calling `stopAll()` at the start of every preview and every
  `ReadAloudButton` click.
- **Re-render behaviour**: removing `localState` from the button changes
  its re-render shape slightly. Covered by the manual checks above.
