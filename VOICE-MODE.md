# Voice Mode — Architecture Overview

Chatsune's voice mode turns the chat UI into a fully-fledged speech interface:
the user presses a key or a button, talks, and hears the reply spoken back. The
assistant can be interrupted mid-sentence the way a human would be. This
document describes how that works end-to-end so you can reason about it, extend
it, or present it to a technical audience.

Target audience: engineers joining the project, or techies evaluating the
design.

---

## 1. What the user gets

The following user-facing features all share the same pipeline:

- **Push-to-talk** — hold `Ctrl+Space` to speak, release to send. One-shot
  utterance.
- **Conversational mode** — a continuous-VAD session: the mic stays open, the
  system hears you when you speak, transcribes, sends, and plays back the
  reply. Loops until the user exits.
- **Auto read-aloud** — assistant messages are spoken automatically when the
  persona has `voice_config.auto_read = true`. Available both in the chat view
  and via the speaker icon on individual messages.
- **Narrator mode** — three render modes (`off`, `play`, `narrate`) split the
  assistant's text into quoted dialogue and surrounding narration, and read
  them in two different voices.
- **Voice modulation** — per-persona speed and pitch for dialogue and
  narration separately. Implemented with a SoundTouch audio worklet so pitch
  and tempo are independent.
- **Tentative barge** — interrupting the assistant no longer requires a
  committed decision at the moment the microphone hears something; the system
  mutes audio on VAD detection, waits for STT to return a real transcript,
  and only tears down the reply if the transcript is non-empty. See §7.
- **Hold-to-keep-talking** — in conversational mode the user can press and
  hold a button so the utterance isn't closed until they release, even if
  they pause mid-sentence.

All features are implemented once, in the `frontend/src/features/voice/`
module tree, and share the same audio capture, audio playback, and
sentencer stack.

---

## 2. Layered architecture

```
+---------------------------------------------------------------+
|                           UI                                   |
|  VoiceButton · ReadAloudButton · ConversationModeButton       |
|  PersonaVoiceConfig · HoldToKeepTalking · ModulationSlider    |
+---------------------------------------------------------------+
|                        Hooks & stores                          |
|  useConversationMode · useCtrlSpace · bargeDecision           |
|  conversationModeStore · voiceSettingsStore                   |
+---------------------------------------------------------------+
|                          Pipeline                              |
|  voicePipeline · streamingSentencer · sentenceSplitter        |
|  audioParser (narrator) · applyModulation                     |
|  streamingAutoReadControl                                     |
+---------------------------------------------------------------+
|                        Infrastructure                          |
|  audioCapture (Silero VAD)  · audioPlayback (Web Audio)       |
|  soundTouchLoader (worklet)                                   |
+---------------------------------------------------------------+
|                      Engines (registry)                        |
|  STTEngine interface · TTSEngine interface                    |
|  EngineRegistry<T>                                            |
+---------------------------------------------------------------+
|                    Integrations plugin layer                   |
|  mistral_voice plugin — registers Mistral STT + TTS engines   |
|  Secrets hydrated from backend over WebSocket                 |
+---------------------------------------------------------------+
|                          Backend                               |
|  No dedicated voice module. The integrations module stores    |
|  encrypted provider credentials and hydrates them on connect. |
+---------------------------------------------------------------+
```

Each layer depends only on the layer below it. The UI talks to hooks and
stores; hooks orchestrate the pipeline; the pipeline drives infrastructure
and engines; engines are registered by integration plugins; the backend only
provides the secrets the plugin needs.

There is deliberately **no backend voice module**. STT and TTS calls are
made directly from the browser to the provider (Mistral). The backend's only
role in voice is to hold the encrypted API key and hand it to the browser
over a short-lived WebSocket event.

---

## 3. Tech stack

**Frontend**

- Vite + React + TypeScript (strict).
- Zustand for state (`conversationModeStore`, `voiceSettingsStore`).
- [`@ricky0123/vad-web`](https://www.npmjs.com/package/@ricky0123/vad-web)
  for voice-activity detection — Silero VAD via ONNX Runtime WASM, loaded
  from CDN the first time it is used.
- [`@soundtouchjs/audio-worklet`](https://www.npmjs.com/package/@soundtouchjs/audio-worklet)
  for independent time-pitch modulation.
- Native Web Audio API (`AudioContext`, `AudioBufferSourceNode`) for
  capture, mixing, and playback.
- Vitest for unit tests.

**Backend**

- FastAPI, Pydantic v2, async-first.
- `backend/modules/integrations/` — generic integration system; voice is
  registered as an integration with `TTS_PROVIDER` and `STT_PROVIDER`
  capabilities.
- Fernet encryption for the provider's API key
  (`UserIntegrationConfig.config_encrypted`).
- Redis Streams for WebSocket event persistence (not voice-specific, but
  every hydration event goes through them).

**Audio provider (current)**

- Mistral's HTTP API for both STT and TTS. Audio is `audio/webm;codecs=opus`
  upload for STT, and MP3/PCM download for TTS. Called from the browser
  directly — no backend proxy.

The stack is deliberately kept narrow. Earlier prototypes used in-browser
WebGPU models (Whisper + Kokoro via `transformers.js`); those were removed
because WebGPU reliability and quantisation behaviour varied too much
across devices for a beta-quality product. Bringing them back would be a
matter of registering two more engines against the same interface.

---

## 4. Frontend: the `voice` feature module

### Infrastructure

These three files own the browser's audio hardware.

- **`audioCapture.ts`** — single interface with two modes:
  - **PTT mode**: `ScriptProcessorNode` on a 16 kHz `AudioContext`, collects
    raw PCM, returns a `Float32Array` on stop.
  - **Continuous mode**: wraps Silero VAD. Emits `onSpeechStart`,
    `onSpeechEnd(Float32Array)`, and `onVADMisfire` (when Silero retracts
    a too-short burst without ever reaching speech-end).
  - A shared AnalyserNode feeds a volume meter via `requestAnimationFrame`.

- **`audioPlayback.ts`** — queue-based Web Audio playback.
  - `enqueue(audio, segment)` — queues an audio buffer with its segment
    metadata (`type`, `text`, `speed`, `pitch`).
  - `stopAll()` — destructive cancel (queue cleared, source stopped,
    callbacks left in place for the next stream).
  - `mute()` / `resumeFromMute()` / `isMuted()` — non-destructive pause for
    Tentative Barge. `mute()` stops the current source but preserves the
    muted entry and the rest of the queue; `resumeFromMute()` re-queues
    the muted entry at the head and restarts playback. `mute()` also
    cancels any pending inter-sentence gap timer so a mute between
    sentences does not bypass the muted state.
  - 24 kHz output context; when modulation is active, each buffer is
    padded with 150 ms of silence so SoundTouch has room to flush its
    internal buffer.

- **`soundTouchLoader.ts`** — lazy AudioWorklet registration for the
  SoundTouch processor. Exposes `ensureSoundTouchReady(ctx)` (idempotent,
  per-context) and `createModulationNode(ctx, speed, pitch)`. If
  registration fails the playback chain falls back to a direct source
  connection: modulation is dropped, everything else still works.

### Pipeline

The pipeline converts an LLM text stream into a queue of spoken sentences.

- **`streamingSentencer.ts`** — the producer. As tokens arrive it buffers
  text, looks for **safe cut points** (sentence endings that are not inside
  an open fenced code block, OOC parens, quote, or emphasis marker), and
  yields `SpeechSegment[]`. This lets TTS start on the first sentence
  while the LLM is still generating the rest of the turn — tangibly
  improving time-to-first-audio.

- **`sentenceSplitter.ts`** — the fine splitter. Used by the parser to
  break a committed chunk into individual sentences with terminal
  punctuation preserved, handling ellipses, decimals, and abbreviations
  (`Dr.`, `z. B.`, `3.14`) without false splits.

- **`audioParser.ts`** — narrator-mode parser. In `play` mode, text
  between asterisks (`*...*`) is narration, everything else is voice.
  In `narrate` mode, quoted text (`"..."`) is voice, everything else is
  narration. Outputs `SpeechSegment[]` with `type: 'voice' | 'narration'`.

- **`applyModulation.ts`** — decorates segments with speed and pitch
  drawn from `persona.voice_config` (different values for dialogue vs.
  narration). Returns the segment unchanged when modulation is neutral
  — this is the fast path, it avoids the SoundTouch detour entirely.

- **`streamingAutoReadControl.ts`** — module-level slot for the active
  streaming read-aloud session. Holds the sentencer, the TTS engine,
  voice presets, mode, and a `cancelled` flag. `cancelStreamingAutoRead()`
  is the single cancellation entry point used by the conversation-mode
  hook and by `ReadAloudButton`; it marks the session cancelled and
  calls `audioPlayback.stopAll()`.

- **`voicePipeline.ts`** — legacy orchestrator for push-to-talk. Owns
  the state machine for PTT: `listening → recording → transcribing →
  waiting-for-llm → speaking`. Conversational mode does not go through
  this module; it has its own hook.

### Hooks & state

- **`useConversationMode.ts`** is the conversational controller — a long
  but focused hook (~470 lines). It:
  - Snapshots and restores per-session settings (reasoning override) on
    entry/exit.
  - Starts and stops `audioCapture.startContinuous`.
  - Owns the state machine (`phase` in the store) and the
    tentative-barge machinery (`bargeIdRef`, `tentativeRef`, 150 ms
    misfire-gate timer).
  - Mediates between the VAD callbacks, the STT engine, and `onSend`
    (the chat-message send path the assistant reply will arrive back
    through).

- **`useCtrlSpace.ts`** — keyboard handler for PTT. Differentiates tap
  vs. hold at a 300 ms threshold so that a quick tap toggles the mic
  and a long hold gates it.

- **`bargeDecision.ts`** — a pure, side-effect-free classifier:
  ```ts
  decideSttOutcome({ transcript, sttBargeId, currentBargeId })
    → 'stale' | 'resume' | 'confirm'
  ```
  Kept separate so the Tentative Barge logic has unit tests that do not
  need audio stubs.

### Engines & registry

- **`engines/registry.ts`** — generic `EngineRegistry<T>` with
  `register / get / list / active / setActive`. Two singletons:
  `sttRegistry` and `ttsRegistry`.
- **`types.ts`** — the `STTEngine` and `TTSEngine` interfaces, plus
  `SpeechSegment`, `VoicePreset`, `NarratorMode`. Adding a new provider
  means implementing these interfaces and calling
  `sttRegistry.register(...)` / `ttsRegistry.register(...)` from a
  plugin's init.

### Components (selected)

- `PersonaVoiceConfig.tsx` — per-persona voice settings: voice preset
  dropdown, speed and pitch sliders (dialogue + narrator), preview
  test-phrase button.
- `ReadAloudButton.tsx` — owns a streaming auto-read session for a
  single assistant message.
- `HoldToKeepTalking.tsx` — overlay button that appears during
  conversational user-speaking phase.

---

## 5. Backend: the integrations layer

The backend does not speak. It stores credentials and relays them to the
browser on demand.

- `backend/modules/integrations/` owns this. An integration is defined by
  an `IntegrationDefinition` with `capabilities: list[IntegrationCapability]`
  — the voice integration lists both `TTS_PROVIDER` and `STT_PROVIDER`.
- Two levels of config:
  - **User-level** — one `UserIntegrationConfig` per (user, integration).
    Non-secret fields (e.g. base URL) are stored plain; `secret: true`
    fields (the API key) are Fernet-encrypted in `config_encrypted` and
    only ever returned to the browser over the hydration WebSocket
    event, never through REST.
  - **Persona-level** — `persona.integration_configs[integration_id]`
    for things that belong to a character rather than a user (e.g.
    `voice_id`, `dialogue_speed`, `narrator_pitch`).
- On WebSocket connect, the backend emits
  `integration.secrets.hydrated` (non-persisted) for each enabled
  integration. The browser keeps those secrets in memory only; they are
  never written to local storage.

For voice, this means:

- The browser holds the Mistral API key for the lifetime of the
  WebSocket session.
- The browser calls Mistral's HTTP endpoints directly for each STT and
  TTS call.
- The backend never sees audio bytes.

This is a deliberate **Bring-Your-Own-Key** design. Each user pays for
their own voice calls; Chatsune does not proxy.

### Backend-proxied integrations

Some voice providers (currently xAI) do not send CORS headers, so the
browser cannot call them directly. For these integrations, the backend
acts as a thin proxy: `POST /api/integrations/{id}/voice/{stt|tts}` and
`GET /api/integrations/{id}/voice/voices`. The API key stays in the
backend; no hydration event is sent.

Each integration declares which mode it uses via
`IntegrationDefinition.hydrate_secrets`:

- `hydrate_secrets=True` (default) — browser-direct, key hydrated over WS
  (Mistral, Lovense).
- `hydrate_secrets=False` — backend-proxied, key never leaves the backend
  (xAI voice).

Backend-proxied voice integrations register a `VoiceAdapter`
(`transcribe`, `synthesise`, `list_voices`) at startup. The proxy route
looks up the adapter by integration id.

---

## 6. Data flow: a conversational turn, end to end

```
User toggles Conversational Mode
          │
          ▼
useConversationMode entry effect
  ├── snapshot reasoning override, force to false
  ├── audioCapture.startContinuous({ onSpeechStart,
  │                                   onSpeechEnd,
  │                                   onVADMisfire })
  └── phase := listening

  … user speaks …

Silero fires onSpeechStart
          │
          ▼
handleSpeechStart
  └── setTimeout(executeBarge, 150 ms)   ← misfire gate

  (150 ms elapse without a misfire retraction)

executeBarge
  ├── bargeId++
  ├── if phase in {thinking, speaking}:
  │     audioPlayback.mute()            ← non-destructive
  │     tentativeRef := true            ← TENTATIVE_BARGE
  └── phase := user-speaking

  … user stops speaking …

Silero fires onSpeechEnd(audio)
          │
          ▼
handleSpeechEnd
  ├── flushHeldAudio (merge any buffered "keep talking" chunks)
  └── transcribeAndSend(merged)

transcribeAndSend
  ├── phase := transcribing
  ├── stt.transcribe(audio)  ─────────►  Mistral STT (browser → API)
  └── decideSttOutcome(text, sttBargeId, bargeIdRef.current)

          │
   ┌──────┴──────────────────────────────────────┐
   ▼                                             ▼
 'resume'                                     'confirm'
 (empty text)                                 (non-empty)
 audioPlayback.resumeFromMute()               cancelStreamingAutoRead()
 phase := speaking                            phase := thinking
                                              onSend(text.trim())
                                              
                                              … normal chat flow …
                                              POST /session/{id}/messages
                                              WebSocket: chat.stream.started
                                              WebSocket: chat.content.delta …
                                                  │
                                                  ▼
                                              StreamingSentencer ingests deltas
                                              yields SpeechSegment[]
                                                  │
                                                  ▼
                                              per segment:
                                                ttsEngine.synthesise(text, voice)
                                                  ─►  Mistral TTS (browser → API)
                                                audioPlayback.enqueue(audio, segment)
                                                  │
                                                  ▼
                                              source.start() → speakers
                                              source.onended → inter-sentence gap
                                                → next segment
                                                
                                              WebSocket: chat.stream.ended
                                                → sentencer.flush()
                                                → last segment queued
                                                
                                              last segment finishes
                                                → phase := listening

  … loop back to listening for the next user utterance …
```

Key observations:

- The same `onSend` path is used as a typed chat message — the backend
  does not know whether the text came from the keyboard or from STT.
- TTS synthesis is **per sentence**, not per turn. First-audio latency
  is bounded by one sentence, not one paragraph.
- There is a **configurable gap** between sentences (`gapMs`, stored on
  the Mistral voice integration config). Default 100 ms; it stops
  sentences from sounding back-to-back when Mistral's audio has very
  clean edges.

---

## 7. Data flow: tentative barge (April 2026)

The problem: a cough, a keyboard burst, or long steady room noise can
pass Silero's 150 ms misfire gate. The old barge handler reacted
immediately — audio torn down, synthesis cancelled, LLM stream
aborted — and so a user who sneezed during a reply would lose the
reply, even though no words were spoken.

The fix is a **two-stage commit**:

```
PLAYING
   │ VAD speech-start passes 150 ms gate
   ▼
TENTATIVE_BARGE
   ├── audio muted (reactive — user hears silence immediately)
   ├── bargeId incremented
   ├── TTS synthesis pipeline untouched
   ├── LLM stream untouched
   └── sentence queue untouched
   │
   ▼ VAD speech-end → STT resolves
   │
   ├── result is empty or whitespace
   │   → resumeFromMute()  (replay from the sentence that was muted)
   │   → PLAYING
   │
   ├── result is non-empty
   │   → cancelStreamingAutoRead()  (destructive, as before)
   │   → onSend(text)
   │   → THINKING
   │
   └── bargeId mismatched (a newer barge has already taken over)
       → drop the result silently
       → newer cycle will decide
```

The serialisation primitive is a monotonic `bargeId` counter. Any
asynchronous result (STT promise, VAD callback) that carries a stale
`bargeId` is ignored. This is what lets the system survive rapid
successive barges without races.

The `mute()` / `resumeFromMute()` pair on `audioPlayback` is the other
half — it preserves the currently-playing entry so that on resume the
user hears the interrupted sentence from its beginning rather than
hearing a cut-off mid-word.

Full design: [`devdocs/superpowers/specs/2026-04-18-tentative-barge-design.md`](devdocs/superpowers/specs/2026-04-18-tentative-barge-design.md).

---

## 8. Design decisions worth noting

**Browser-direct provider calls, not a backend proxy.**
Audio bytes are large and latency-sensitive. Routing them through
FastAPI would double bandwidth and add a round-trip. The only reason
to route would be to hide the API key — and the hydration-over-WS
pattern (§5) keeps the key out of persistent storage while letting
the browser call the provider directly.

**One sentencer, many consumers.**
The same `StreamingSentencer` drives PTT playback, auto-read on new
messages, and the conversational mode TTS. The parser, splitter,
and modulation decorator do not know which consumer they are feeding.
Adding a new playback context means composing these pieces, not
re-implementing sentence logic.

**Non-destructive mute as a primitive.**
`audioPlayback.mute()` / `resumeFromMute()` are primitives, not
features. The Tentative Barge feature is built on top of them, but the
same primitives could be used for other pause/resume surfaces (e.g.
a user-visible "pause" button, browser-tab-blur auto-pause).

**Narrator mode is orthogonal.**
The parser emits tagged segments; every downstream layer — sentencer,
modulation, playback — handles `voice` and `narration` uniformly.
Narrator mode is essentially "which tag is spoken with which voice
preset", and a second voice per persona is a straightforward
extension.

**VAD has two lines of defence against false positives.**
First line: Silero's own misfire retraction plus our 150 ms deferral
— handles sub-second bursts (chair creak, single keyboard click).
Second line: Tentative Barge — handles longer non-speech energy
(coughs, sustained typing, door slam) that VAD cannot distinguish from
speech but STT can.

**Single hook owns the conversational state machine.**
`useConversationMode.ts` is longer than most files in the codebase,
and deliberately so. Splitting it into several hooks would multiply
the ref-forwarding surface (every callback captures six or seven
refs). Keeping it in one place makes the transitions readable.

---

## 9. Where to look

| Concern | File |
| --- | --- |
| Conversational state machine | [`frontend/src/features/voice/hooks/useConversationMode.ts`](frontend/src/features/voice/hooks/useConversationMode.ts) |
| Tentative barge decision | [`frontend/src/features/voice/hooks/bargeDecision.ts`](frontend/src/features/voice/hooks/bargeDecision.ts) |
| PTT state machine | [`frontend/src/features/voice/pipeline/voicePipeline.ts`](frontend/src/features/voice/pipeline/voicePipeline.ts) |
| Audio capture (VAD) | [`frontend/src/features/voice/infrastructure/audioCapture.ts`](frontend/src/features/voice/infrastructure/audioCapture.ts) |
| Audio playback + mute/resume | [`frontend/src/features/voice/infrastructure/audioPlayback.ts`](frontend/src/features/voice/infrastructure/audioPlayback.ts) |
| SoundTouch modulation | [`frontend/src/features/voice/infrastructure/soundTouchLoader.ts`](frontend/src/features/voice/infrastructure/soundTouchLoader.ts) |
| Streaming sentencer | [`frontend/src/features/voice/pipeline/streamingSentencer.ts`](frontend/src/features/voice/pipeline/streamingSentencer.ts) |
| Sentence splitter | [`frontend/src/features/voice/pipeline/sentenceSplitter.ts`](frontend/src/features/voice/pipeline/sentenceSplitter.ts) |
| Narrator parser | [`frontend/src/features/voice/pipeline/audioParser.ts`](frontend/src/features/voice/pipeline/audioParser.ts) |
| Modulation decorator | [`frontend/src/features/voice/pipeline/applyModulation.ts`](frontend/src/features/voice/pipeline/applyModulation.ts) |
| Active-session slot | [`frontend/src/features/voice/pipeline/streamingAutoReadControl.ts`](frontend/src/features/voice/pipeline/streamingAutoReadControl.ts) |
| Engine interfaces | [`frontend/src/features/voice/types.ts`](frontend/src/features/voice/types.ts) |
| Engine registry | [`frontend/src/features/voice/engines/registry.ts`](frontend/src/features/voice/engines/registry.ts) |
| Engine resolver | [`frontend/src/features/voice/engines/resolver.ts`](frontend/src/features/voice/engines/resolver.ts) |
| Mistral voice plugin | [`frontend/src/features/integrations/plugins/mistral_voice/`](frontend/src/features/integrations/plugins/mistral_voice/) |
| xAI voice plugin (frontend) | [`frontend/src/features/integrations/plugins/xai_voice/`](frontend/src/features/integrations/plugins/xai_voice/) |
| Backend integrations | [`backend/modules/integrations/`](backend/modules/integrations/) |
| xAI voice adapter (backend) | [`backend/modules/integrations/_voice_adapters/_xai.py`](backend/modules/integrations/_voice_adapters/_xai.py) |
| Voice proxy routes | [`backend/modules/integrations/_handlers.py`](backend/modules/integrations/_handlers.py) |

### Relevant design specs

- [`2026-04-13-voice-mode-design.md`](devdocs/superpowers/specs/2026-04-13-voice-mode-design.md) — initial voice mode design.
- [`2026-04-17-voice-integrations-design.md`](devdocs/superpowers/specs/2026-04-17-voice-integrations-design.md) — moving voice onto the integrations layer.
- [`2026-04-17-voice-auto-read-and-narrator-design.md`](devdocs/superpowers/specs/2026-04-17-voice-auto-read-and-narrator-design.md) — centralised read-aloud state and three-mode parser.
- [`2026-04-17-voice-sentence-streaming-design.md`](devdocs/superpowers/specs/2026-04-17-voice-sentence-streaming-design.md) — sentence-level TTS streaming with configurable gap.
- [`2026-04-18-soundtouch-voice-modulation-design.md`](devdocs/superpowers/specs/2026-04-18-soundtouch-voice-modulation-design.md) — independent time-pitch modulation.
- [`2026-04-18-tentative-barge-design.md`](devdocs/superpowers/specs/2026-04-18-tentative-barge-design.md) — two-stage commit for barge-in.
- [`2026-04-19-xai-voice-integration-design.md`](devdocs/superpowers/specs/2026-04-19-xai-voice-integration-design.md) — xAI as a second voice provider; backend-proxied integrations.
