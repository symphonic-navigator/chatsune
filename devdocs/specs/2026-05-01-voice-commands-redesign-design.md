# Voice Commands — Redesign Design

**Date:** 2026-05-01
**Status:** Approved (pre-implementation)
**Predecessor:** `2026-05-01-voice-commands-companion-lifecycle-design.md` (Companion Lifecycle, just merged to master)
**Affected modules:** `frontend/src/features/voice-commands/` (rename + behavioural changes), `frontend/src/features/voice/` (UI), `frontend/src/features/chat/` (cockpit + ChatView)

---

## 1. Goal

Replace the `companion`-triggered voice commands with a `voice`-triggered redesign that is more robust against STT errors, semantically clearer, and visually represented in the UI. The state previously called *companion off* becomes *voice paused*; *companion on* becomes *voice active*. Both lifecycle states are surfaced in the cockpit and the top bar, and either indicator can be clicked to leave the paused state.

The redesign keeps the foundation laid by the predecessor spec — local Vosk OFF-state STT, audio cues, response channel, dispatcher with `onTriggerWhilePlaying` semantics — and changes only the surface: trigger word, synonym set, lifecycle naming, UI indicators, and one new strict-reject heuristic in the dispatcher.

## 2. Why now

The companion-lifecycle implementation shipped, but on-device testing surfaced eight issues that together amount to a redesign rather than a patch:

1. STT backends mishear *companion* (e.g. as *pennion*); reliability is too low for a wake word.
2. STT also mishears *off* as *of*; the matcher must accept the slip without silently routing it to the LLM.
3. End-of-utterance punctuation must be stripped before matching (already correct in the current normaliser; verified, no change).
4. *companion status* could not be reliably triggered in the OFF state; the spec was complete but the path is fragile.
5. The *Hold to keep talking* button stayed visible during OFF mode despite having no function there.
6. There is no visual indicator that the user is in OFF mode; users lose track of state.
7. Users expect to be able to leave OFF mode by clicking the same button that took them in.
8. *off / on* are technically correct but conceptually wrong: the assistant isn't *off*, the *voice* is *paused*. Renaming makes the mental model match the UX.

Patching each issue piecemeal would leave the implementation half-renamed and half-the-old-design. A clean redesign while the feature is still fresh is the cheaper path.

## 3. Non-goals

- Error toast and audible error cue when a 2-token `voice <unknown>` utterance is rejected. Tracked as a follow-up via a `// TODO` comment in the dispatcher; will get its own spec when prioritised.
- Custom wake words (e.g. user-configured aliases for `voice`). One trigger word fits all users for now.
- Persistence of the lifecycle state across page reloads. Same as predecessor — `paused` is meaningless outside an active continuous-voice session.
- Vosk model swap, confidence-threshold tuning, or any other recogniser-internal change. Only the grammar's accept-set and distractor list change.
- A separate UI surface in `VoiceTab.tsx` for command settings. Synonyms are hard-coded; the design assumes consistent vocabulary, not user customisation.

---

## 4. Terminology and state model

The lifecycle becomes user-facing first, code second.

```ts
type VoiceLifecycle = 'active' | 'paused'
```

User-visible naming throughout UI, toasts, and logs is **active** / **paused**. Spoken commands accept three synonym sets per action so the user can keep talking even when an STT slip turns *pause* into something unexpected.

| Predecessor | Redesign |
|---|---|
| `companionLifecycleStore` | `voiceLifecycleStore` |
| `state: 'on' \| 'off'` | `state: 'active' \| 'paused'` |
| `setOn()` / `setOff()` | `setActive()` / `setPause()` |
| `useCompanionLifecycleStore` | `useVoiceLifecycleStore` |
| `companionCommand` (handler) | `voiceCommand` (handler) |
| `handlers/companion.ts` | `handlers/voice.ts` |

The `reset()` method keeps its name; only the target value changes (was `'on'`, now `'active'`). It continues to be invoked from `useConversationMode.teardown(...)` on continuous-voice stop, preserving the predecessor invariant that every fresh continuous-voice session starts active.

Cue vocabulary is **not** renamed: `CueKind = 'on' | 'off'` continues to denote the *acoustic* tone shape (rising vs. falling), not the lifecycle state. UI mapping at the call site: pause action plays the `'off'` cue; resume action plays the `'on'` cue.

---

## 5. Trigger, synonyms, and matcher behaviour

### 5.1 Single trigger word

`voice` is the trigger. On-device tests against xAI Voice and Mistral Voice playgrounds (10× repetitions each) confirmed the word transcribes reliably; *companion* did not.

### 5.2 Synonym sets

Inside the `voiceCommand.execute(body)` handler:

```ts
const PAUSE_SYNONYMS  = new Set(['pause', 'off', 'of'])
const ACTIVE_SYNONYMS = new Set(['continue', 'on', 'resume'])
const STATUS_SYNONYMS = new Set(['status', 'state'])
```

Dispatch table:

| Sub-token (after normalise/trim) | Action | Cue | Toast (variant b) | `onTriggerWhilePlaying` |
|---|---|---|---|---|
| ∈ `PAUSE_SYNONYMS` | `setPause()` | `'off'` | `Paused — say "voice on" to resume.` | static `'abandon'` |
| ∈ `ACTIVE_SYNONYMS` | `setActive()` | `'on'` | `Listening — say "voice off" to pause.` | static `'abandon'` (no-op when entering from paused — no Group exists); per-call `'resume'` on the already-active idempotent path |
| ∈ `STATUS_SYNONYMS` | none | `'on'` if active, `'off'` if paused | `Listening — say "voice off" to pause.` if active, `Paused — say "voice on" to resume.` if paused | per-call `'resume'` (status must never interrupt) |
| else | reject | none | none | (handled by strict-reject path; see §5.3) |

### 5.3 Strict-reject for 2-token `voice <unknown>`

In `dispatcher.tryDispatchCommand`, before the normal trigger lookup:

```ts
if (tokens.length === 2 && tokens[0] === 'voice' && !isKnownVoiceSub(tokens[1])) {
  console.warn('[VoiceCommand] Rejected 2-token "voice <unknown>": tokens=%o', tokens)
  // TODO: add error toast and audible feedback with error sound
  return { dispatched: true, onTriggerWhilePlaying: 'resume' }
}
```

`isKnownVoiceSub(token)` returns `true` if the token is in `PAUSE_SYNONYMS ∪ ACTIVE_SYNONYMS ∪ STATUS_SYNONYMS`. The helper lives in `voice-commands` next to the synonym sets so all related state stays together.

Why this matters:

- `dispatched: true` ensures the rejected utterance does **not** fall through to the LLM. A user who tried to give a command and was misheard should not see their command go out as a chat message.
- `'resume'` protects an in-flight persona reply: the user clearly intended a command, not a barge-in.
- The 2-token guard limits the rejection to short utterances — the most common form of a misheard command. Sentences of 3+ tokens that happen to start with *voice* (`voice that's a great idea`, `voice over of the speaker`) fall through to the LLM as before.

### 5.4 Ignored variants

- `voice off` while already `paused` is a no-op — it is also omitted from the Vosk OFF-state grammar (see §6) so it never reaches the dispatcher in that state.
- `voice on` while already `active` is idempotent: handler returns `{ level: 'info', cue: 'on', displayText: 'Listening — say "voice off" to pause.', onTriggerWhilePlaying: 'resume' }`.

### 5.5 Punctuation

`normaliser.normalise()` already strips `[.,;:!?…„"'']` (Unicode pattern, `normaliser.ts:27`). No change. Existing test `'Companion off.' → ['companion', 'off']` is updated in this redesign to `'Voice off.' → ['voice', 'off']`.

---

## 6. Vosk OFF-state grammar

The Vosk recogniser only listens while lifecycle is `paused`. In that state, *pausing again* is a no-op, so the accept set covers only the resume and status actions:

```ts
ACCEPT_TEXTS = new Set([
  'voice on',
  'voice continue',
  'voice resume',
  'voice status',
  'voice state',
])
```

Grammar follows the pattern from the predecessor (VOSK-STT.md pitfalls #6 and #7):

```ts
VOSK_GRAMMAR = [
  // Accept set
  'voice on', 'voice continue', 'voice resume', 'voice status', 'voice state',

  // Phonetic distractors of 'voice' — standalone
  'noise', 'choice', 'boys', 'voice', 'poise', 'vice', 'rice',

  // Phonetic distractors with each subcommand (every standalone distractor
  // also appears here; VOSK-STT.md pitfall #7 — without the second-word
  // forms, the second word collapses onto the accept set when the first
  // word is misheard).
  'noise on',  'noise continue',  'noise resume',  'noise status',  'noise state',
  'choice on', 'choice continue', 'choice resume', 'choice status', 'choice state',
  'boys on',   'boys continue',   'boys resume',   'boys status',   'boys state',
  'poise on',  'poise continue',  'poise resume',  'poise status',  'poise state',
  'vice on',   'vice continue',   'vice resume',   'vice status',   'vice state',
  'rice on',   'rice continue',   'rice resume',   'rice status',   'rice state',

  // Garbage model
  '[unk]',
]
```

`voice` appears as a standalone distractor as well: a user who says *voice* and trails off must drop, not collapse onto an accept entry.

Confidence threshold (`WAKE_CONF_THRESHOLD = 0.95`) is unchanged; the words remain high-confidence-recognisable.

The Vosk model itself, the model loader, the recogniser lifecycle (`init/feed/dispose`), and the download pipeline (script + Dockerfile + Workbox precache) are all unchanged.

---

## 7. UI changes

### 7.1 Cockpit VoiceButton (`features/chat/cockpit/buttons/VoiceButton.tsx`)

`_voiceState.deriveVoiceUIState(...)` gains a new input `lifecycle: VoiceLifecycle` and a new output kind:

```ts
type VoiceUIState =
  | { kind: 'disabled' }
  | { kind: 'normal-off' }
  | { kind: 'normal-on' }
  | { kind: 'normal-playing' }
  | { kind: 'live-mic-on' }
  | { kind: 'live-mic-muted' }
  | { kind: 'live-playing' }
  | { kind: 'live-paused' }       // ← new
```

Derive rule: when `liveMode && lifecycle === 'paused'`, return `'live-paused'`. This branch takes precedence over `'live-mic-on'` and `'live-mic-muted'` — in paused mode, the mute toggle is irrelevant; the click resumes.

Click-handler branch in `VoiceButton.onClick`:

```ts
case 'live-paused': return useVoiceLifecycleStore.getState().setActive()
```

Visual (matches the validated mockup):

- Border `border-amber-400/55`, background `bg-amber-400/15`, foreground `text-amber-400`.
- Pulse animation (Tailwind `animate-pulse` or a custom keyframe with a brief amber glow).
- Mic SVG rendered with the existing strikethrough variant (`<MicIcon muted={true} />` from the same component file).
- Label: `"Voice paused"`.
- Panel status: `"Voice paused — click to resume"`.

If `CockpitButton`'s `state` discriminator (`'idle' | 'active' | 'playback' | 'disabled'`) needs a new `'paused'` value, the implementation plan handles that addition; the spec leaves the call shape open.

### 7.2 Top-bar ConversationModeButton (`features/voice/components/ConversationModeButton.tsx`)

New props:

```ts
lifecycle: VoiceLifecycle    // 'active' | 'paused'
onResume?: () => void        // called on click when lifecycle === 'paused'
```

Render branches:

| `active` | `lifecycle` | Pill |
|---|---|---|
| `false` | (any) | gold/35 `"Voice chat"` (existing) |
| `true` | `'active'` | gold + slow pulse `"Live"` with phase dot (existing) |
| `true` | `'paused'` | **amber + fast pulse `"Paused"`, strikethrough mic, click → `onResume()`** |

Caller (the top-bar component that mounts this button) reads `useVoiceLifecycleStore` and passes `lifecycle` and `onResume={() => setActive()}`.

Consequence: exiting live-mode entirely *while paused* requires two clicks (resume → toggle off). Acceptable; exiting from a paused state is rare.

### 7.3 HoldToKeepTalking visibility (`features/chat/ChatView.tsx`)

Render condition gains a lifecycle gate:

```tsx
{conversationActive
  && !conversationMicMuted
  && voiceLifecycle === 'active'                           // ← new
  && (conversationPhase === 'user-speaking' || conversationPhase === 'held') && (
  <HoldToKeepTalking ... />
)}
```

`voiceLifecycle` is read via `useVoiceLifecycleStore((s) => s.state)`.

### 7.4 Unchanged UI

- `cuePlayer` — same on/off cue acoustics.
- `responseChannel` and toast rendering — only the toast strings change, not the channel.
- `TranscriptionOverlay`, `ChatInput`, generic voice UI — untouched.

---

## 8. Files affected

### 8.1 voice-commands module

Rename:

- `companionLifecycleStore.ts` → `voiceLifecycleStore.ts`
- `handlers/companion.ts` → `handlers/voice.ts`
- `__tests__/companionLifecycleStore.test.ts` → `voiceLifecycleStore.test.ts`
- `__tests__/handlers/companion.test.ts` → `__tests__/handlers/voice.test.ts`

Behavioural change:

- `voiceLifecycleStore.ts` — new state shape and setter names.
- `handlers/voice.ts` — new trigger, synonym sets, dispatch table, toast strings.
- `dispatcher.ts` — strict-reject pre-check with `// TODO` comment for the follow-up.
- `vosk/grammar.ts` — new accept set, new distractor matrix.
- `index.ts` — re-exports renamed (`useVoiceLifecycleStore`, `voiceCommand`).
- `types.ts` — if `CompanionLifecycle` was exported, rename to `VoiceLifecycle`.

Tests:

- `__tests__/dispatcher.test.ts` — strict-reject coverage (2-token unknown, 3+ token fall-through, known-sub passthrough).
- `__tests__/vosk/grammar.test.ts` — new accept set, distractor coverage assertions.
- All renamed test files — adapted to new symbol names and assertions.

### 8.2 voice module

- `components/ConversationModeButton.tsx` — new `lifecycle` and `onResume` props, new paused-render branch.
- `components/ConversationModeButton.test.tsx` — paused-state tests, click-routing tests.
- `hooks/useConversationMode.ts` — store-import rename only; existing `reset()` call preserved.

### 8.3 chat module

- `cockpit/buttons/_voiceState.ts` — new `'live-paused'` kind, derive rule with precedence.
- `cockpit/buttons/__tests__/_voiceState.test.ts` — new state coverage.
- `cockpit/buttons/VoiceButton.tsx` — click-handler branch, visual mapping (amber, pulse, strikethrough mic), panel texts.
- `cockpit/CockpitButton.tsx` — only if a `'paused'` value needs to be added to the `state` discriminator.
- `ChatView.tsx` — `HoldToKeepTalking` lifecycle gate, top-bar wiring (`lifecycle` + `onResume` to `ConversationModeButton`).

### 8.4 Out of scope

- `cuePlayer.ts`, `responseChannel.ts` — unchanged.
- Vosk download script, Dockerfile, Workbox precache — unchanged.

### 8.5 Module boundaries

The `voice-commands` module continues to expose its public API via `index.ts`. Cross-module callers (`useConversationMode`, `ConversationModeButton`, `ChatView`) import only from `'@/features/voice-commands'` (or the equivalent relative path) — no `_internal` imports.

---

## 9. Manual verification

To be run on a real device with microphone, browser, and a warmed-up Vosk model. Each step has explicit pass criteria.

### 9.1 Trigger word and synonyms (active mode)

Setup: continuous-voice started, lifecycle = `active`.

| Spoken phrase | Expected outcome |
|---|---|
| `Voice off` | Toast `Paused — say "voice on" to resume.` + `'off'` cue, state → paused |
| `Voice pause` | as above |
| `Voice of` (STT slip) | as above |
| `Voice on` (back from paused) | Toast `Listening — say "voice off" to pause.` + `'on'` cue, state → active |
| `Voice continue` | as above |
| `Voice resume` | as above |
| `Voice status` | toast for the current state, no state change, matching cue |
| `Voice state` | as `voice status` |

Pass when: all eight phrases drive the correct lifecycle transition with the correct toast and cue.

### 9.2 Strict-reject (2-token `voice <unknown>`)

Setup: active mode.

Action: say `Voice nope`.

Pass when:

- The persona does **not** answer with an LLM reply.
- The browser console contains `[VoiceCommand] Rejected 2-token "voice <unknown>": tokens=['voice', 'nope']`.
- The dispatcher source carries the `// TODO: add error toast and audible feedback with error sound` comment at this site.

### 9.3 *voice* as a content word (3+ tokens)

Setup: active mode.

Action: say `Voice mode is great` or `Voice that's a good idea`.

Pass when: the sentence reaches the LLM as a normal prompt; the persona answers it; no reject log; no lifecycle change.

### 9.4 Paused-mode Vosk path

Setup: utter `Voice off` from active mode → lifecycle = `paused`. Vosk model is loaded (the tab has been in paused at least once, or the warm-up `init()` has resolved).

Test each phrase individually:

1. `Voice on` → lifecycle → active, `'on'` cue.
2. `Voice continue` → as 1.
3. `Voice resume` → as 1.
4. `Voice status` → toast for the (paused) state, no change.
5. `Voice state` → as 4.
6. `Voice off` → silently dropped (omitted from Vosk grammar).
7. Any non-command sentence → no state change, no audio leaves the browser; only the Vosk reject logs appear in the console.

Pass when: 1–5 dispatch correctly; 6 and 7 produce no visible effect.

### 9.5 UI indicators

Setup: active mode → say `Voice off` → in paused.

Pass when (visual, no inspector required):

- Cockpit VoiceButton: amber, pulsing, mic struck through.
- Top-bar pill: amber, pulsing, label `Paused`, mic struck through.
- HoldToKeepTalking is **not** rendered, even when speaking would normally trigger `'user-speaking'`.

### 9.6 Click-to-resume

Setup: paused mode.

Actions:

1. Click the cockpit VoiceButton once → lifecycle = active, `'on'` cue, cockpit button returns to blue (mic listening).
2. Say `Voice off` again, then click the top-bar pill → lifecycle = active, top-bar pill returns to gold `Live`.

Pass when: both buttons resume from paused; no accidental exit-live-mode; no mute toggle.

### 9.7 Lifecycle reset on continuous-voice stop

Setup: paused mode → top-bar pill click (resume → active) → top-bar pill click (live mode off) → top-bar pill click (live mode on again).

Pass when: on the fresh entry, lifecycle = `active` (cockpit blue, pill gold `Live`), not `paused`. No persistence leak.

### 9.8 Trailing punctuation

Setup: active mode. Upstream STT delivers transcripts with sentence-final punctuation (cannot be forced by the test plan; observed during normal use).

Action: when STT delivers `Voice off.` with a trailing period.

Pass when: console logs `[VoiceCommand] dispatched: trigger=voice body=off` (without the period); pause transition succeeds.

---

## 10. Open follow-ups

Tracked in code, not in this spec:

- Error toast and audible error cue when a 2-token `voice <unknown>` is rejected (5.3). `// TODO` left in the dispatcher; will become its own spec when prioritised.
