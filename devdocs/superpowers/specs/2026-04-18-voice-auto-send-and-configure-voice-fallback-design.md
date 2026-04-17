# Voice Auto-Send Toggle & Configure-Voice Fallback — Design

Status: Approved
Scope: Frontend-only

## Context

Voice interaction in Chatsune currently works as follows:

- A Push-to-Talk button records the user's voice. When released, the recording
  is transcribed and the resulting text is written into the chat input field.
  The user then taps Send manually.
- A never-officially-shipped "Continuous" input mode exists behind a UI
  toggle on the **Display** sub-tab of the user modal. Its implementation in
  `ChatView.tsx` auto-sends the transcription after 800 ms. This mode is
  considered incorrectly implemented and is being removed from the UI. The
  proper continuous experience will return later as a VAD-based mode.
- Each Assistant message can show a "Read" (TTS) button. The button only
  appears when (a) the user has a TTS integration configured (`ttsReady`) and
  (b) the persona has a `voice_id` selected for that integration. Otherwise
  the button disappears with no visible way for the user to fix either
  condition from within the chat view.

Two small feature requests — both frontend-only:

1. **Auto-send transcription.** A user-level setting that, when on, sends the
   Push-to-Talk transcription as soon as it arrives instead of placing it in
   the chat input for manual review. This gets most of the value of a
   hands-free experience without building VAD.
2. **Configure-voice fallback button.** When the Read button cannot be shown,
   show an unobtrusive "Configure voice" button in its place that opens the
   persona's voice configuration directly.

## Non-goals

- Server-side persistence of voice preferences. Voice settings stay
  browser-local via `localStorage`, matching the current `voiceSettingsStore`.
- Re-implementation of the Continuous / VAD mode. The UI toggle is removed
  and the auto-send branch in `ChatView.tsx` becomes the single auto-send
  path. Bringing back VAD is a future iteration, not this one.
- Expanding the persona-voice-configuration UI itself. The fallback button
  only opens the existing Voice sub-tab of the persona overlay.
- Adding a deep-link to the Integrations tab when no TTS integration exists.
  The persona voice configuration already surfaces the missing integration
  clearly enough for this iteration.

## Feature 1 — Voice Auto-Send Toggle

### New sub-tab under Settings

A new Voice sub-tab is added to the user-modal navigation, positioned
immediately after Display under the Settings top tab. The Voice sub-tab
contains a single setting for now: an on/off toggle labelled **Automatically
send transcription**, default off.

Helper text under the toggle:
> When on, your transcribed speech is sent as soon as you release
> Push-to-Talk — no extra tap.

Styling matches the existing toggles on the Display sub-tab (Vibration,
White Script): same label colour, same pill-style On/Off button, same
font-mono label treatment.

### Removal of Input-Mode buttons

The existing Push-to-Talk / Continuous button group — currently rendered by
`VoiceSettings.tsx` and embedded at the bottom of `SettingsTab.tsx` — is
removed entirely from the UI. The `VoiceSettings.tsx` component file is
deleted because it becomes unused. Its import and JSX usage in
`SettingsTab.tsx` are removed along with the preceding divider.

### Store changes

`voiceSettingsStore.ts` gains one field and its setter:

```ts
autoSendTranscription: boolean            // default false
setAutoSendTranscription(value: boolean): void
```

The existing `inputMode` field and `setInputMode` setter stay on the state
for localStorage schema compatibility (older browsers already have
`voice-settings` entries persisted). On store hydration, `inputMode` is
forced to `'push-to-talk'` regardless of what is in localStorage — this is
the hard-coded input mode for now. Nothing in the app will ever call
`setInputMode` again.

### Transcription callback in ChatView

The transcription callback in `ChatView.tsx` currently branches on
`voiceInputMode`. That branch is replaced by a branch on
`autoSendTranscription`:

```ts
onTranscription: (text) => {
  setTranscription(text)
  if (autoSendTranscription && text.trim()) {
    setTimeout(() => {
      handleSend(text)
      setTranscription('')
    }, 800)
  } else {
    chatInputRef.current?.setText(text)
    setTimeout(() => setTranscription(''), 1500)
  }
}
```

The 800 ms delay is preserved so the transcription overlay flashes briefly
before the message is sent — giving the user a chance to see what was
transcribed. The `voiceInputMode` read from the store is removed; the
effect's dependency array is updated accordingly to track
`autoSendTranscription` instead.

## Feature 2 — Configure-Voice Fallback Button

### New persona-overlay store

A minimal Zustand store holds the persona-overlay UI state:

```ts
interface PersonaOverlayState {
  open: boolean
  personaId: string | null
  activeTab: PersonaTabId | null      // 'general' | 'voice' | …
  openAtTab(personaId: string, tab: PersonaTabId): void
  close(): void
}
```

Location: `frontend/src/app/components/persona-overlay/personaOverlayStore.ts`.

No `persist` middleware — this is transient UI state. The store is the
single source of truth for "is the persona overlay open, for which persona,
and on which tab?".

### Existing overlay opening paths migrate to the store

All existing places that open the persona overlay today (personas list,
persona-switcher, any other entry point) are switched to call
`openAtTab(personaId, defaultTab)` instead of setting local component
state. This keeps a single source of truth — there is no world where part
of the app uses the store and part uses local state.

`PersonaOverlay.tsx` reads `open`, `personaId`, and `activeTab` from the
store and uses them directly as its source of truth — there is no separate
internal active-tab state. Close actions (overlay dismiss, backdrop click,
Escape) call `store.close()`. Changing tabs from within the overlay writes
back to the store via `openAtTab(personaId, newTab)`.

### Fallback button in ReadAloudButton

The current guard in `ReadAloudButton.tsx`:

```ts
if (!ttsReady || !voiceId) return null
```

is replaced with a fallback button rendered in place of the Read button.
The fallback uses the same icon as the Read button but with:

- distinct tooltip/aria-label "Configure voice"
- dimmer colour (e.g. `text-white/35 hover:text-white/65`) to signal
  secondary priority
- onClick handler: `personaOverlayStore.getState().openAtTab(personaId, 'voice')`

The button is shown in **both** failure cases:

- `!ttsReady` (no TTS integration configured anywhere)
- `ttsReady && !voiceId` (integration present but persona has no voice)

In the first case, the persona voice configuration shows an empty voice
dropdown with its existing empty-state copy. That is acceptable visible
feedback for this iteration.

### Persona-ID plumbing

`AssistantMessage` receives a new required `personaId: string` prop and
passes it to `ReadAloudButton`. `MessageList` already knows the active
session's `personaId` and supplies it to each rendered `AssistantMessage`.
A chat message always belongs to a session with a persona, so the prop is
unconditionally required — no fallback path for a missing id.

## Files touched

Frontend only:

- `frontend/src/app/components/user-modal/userModalTree.ts` — add `'voice'`
  to `SubTabId` and to the `settings` children array (after `'display'`)
- `frontend/src/app/components/user-modal/VoiceTab.tsx` — new
- `frontend/src/app/components/user-modal/SettingsTab.tsx` — remove
  `VoiceSettings` import, JSX usage, preceding divider
- `frontend/src/app/components/user-modal/UserModal.tsx` — wire the new
  sub-tab to render `VoiceTab`
- `frontend/src/features/voice/components/VoiceSettings.tsx` — delete
- `frontend/src/features/voice/stores/voiceSettingsStore.ts` — add
  `autoSendTranscription` + setter, hydrate `inputMode` as `'push-to-talk'`
- `frontend/src/features/chat/ChatView.tsx` — replace `voiceInputMode`
  branch with `autoSendTranscription` branch; update effect deps
- `frontend/src/app/components/persona-overlay/personaOverlayStore.ts` — new
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — read
  open / personaId / activeTab from the store; call `close()` on dismiss
- `frontend/src/features/voice/components/ReadAloudButton.tsx` — replace
  `return null` guard with fallback button; accept `personaId` prop
- `frontend/src/features/chat/AssistantMessage.tsx` — accept and forward
  `personaId`
- `frontend/src/features/chat/MessageList.tsx` — pass active session's
  `personaId` to each `AssistantMessage`
- Any current persona-overlay opener (personas list, switcher) — migrate
  to `personaOverlayStore.openAtTab`

## Verification

- `pnpm run build` clean after changes
- `pnpm tsc --noEmit` clean
- Manual smoke test in the browser:
  1. New Voice sub-tab appears in user modal after Display; toggle
     persists across reloads
  2. With Auto-send off and PTT used: transcription lands in the chat
     input as before
  3. With Auto-send on and PTT used: transcription flashes in the
     overlay for ~800 ms and is then sent without further interaction
  4. Display sub-tab no longer shows the Push-to-Talk / Continuous
     button group
  5. Chat view with a persona that has no `voice_id`: "Configure voice"
     button appears below the assistant reply; clicking it opens the
     persona overlay on the Voice tab for that persona
  6. Chat view with no TTS integration at all: same "Configure voice"
     button appears; clicking it opens the persona overlay on the Voice
     tab, which shows an empty voice dropdown
  7. Persona overlay opened through existing routes (personas list,
     switcher) still works; closing resets the store

## Risks and open points

- None identified.
