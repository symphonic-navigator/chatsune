# Voice Commands — Foundation Design

**Date:** 2026-04-30
**Status:** Approved (pre-implementation)
**Scope:** Foundation only. Part 2 (system-voice + cache) and part 3 (companion commands) live in follow-up sessions.
**Affected modules:** new `frontend/src/features/voice-commands/`; small touches to `frontend/src/features/voice/hooks/useConversationMode.ts`, `frontend/src/features/integrations/types.ts`, `frontend/src/features/integrations/pluginLifecycle.ts`.

---

## 1. Goal

Introduce an in-chat command system reachable **only through continuous voice mode**. Commands bypass the LLM, never appear in the chat stream, and are executed directly by frontend handlers. The foundation must support core built-in commands and per-integration trigger words registered through the existing plugin lifecycle.

This first spec ships the foundation plus one trivial built-in (`debug`) that proves the full pipeline end-to-end with an ugly alert box.

## 2. Why voice-only

The feature exists to enable **hands-free always-on operation**. Reading the same trigger words from the text input would either pollute regular chat or require a parallel parser path with no benefit. Continuous voice is already the long-session mode (see project memory `continuous voice = long-session mode`); commands branch from it.

## 3. Non-goals

- Companion commands (`companion off/on/status`) — part 3, blocked on part 2.
- Hue, Lovense, or any other integration-provided trigger words — added by the integration plugin itself, not this spec.
- System-voice playback for command responses — part 2 (`devdocs/specs/_brief-voice-commands-part2-system-voice.md`).
- Cache layer for system-voice utterances — part 2.
- Settings UI for system-voice selection — part 2.
- Backend-side command audit logging — additive later if needed.
- Discovery / "what commands are available" UX — out of scope until at least three concrete commands exist.

---

## 4. Design Decisions (Resolved during Brainstorming)

| # | Decision | Rationale |
|---|---|---|
| 1 | Voice-only, never text input | Hands-free is the entire point; text input has the LLM as its consumer. |
| 2 | Continuous voice only, never push-to-talk | PTT is one-shot; commands belong to the always-on mode. |
| 3 | First-word **exact** match after normalisation | "companionship" must not trigger "companion"; tokenisation gives word boundaries for free. |
| 4 | Tolerant normalisation: lowercase, trim, collapse whitespace, strip punctuation, strip a small list of leading fillers | Real STT output is noisy; strict matching without tolerance breaks 95% of real attempts. |
| 5 | Trigger matched + body unrecognised → swallow utterance + emit error response through the same response channel | "Optimistic, tolerant parsing": once the trigger is heard, the dispatcher owns the utterance. Falling through to the LLM would let "companion banana" become a chat prompt, which is worse. |
| 6 | Response channel: handler returns `{level, spokenText, displayText}`; v1 renders `displayText` as toast, ignores `spokenText`. Part 2 adds system-voice playback of `spokenText` with toast fallback when no system voice is configured. | Stable interface across v1 and v2; handlers never need to be revisited. |
| 7 | Per-handler `onTriggerWhilePlaying: 'abandon' \| 'resume'` flag, **required** on every handler | "companion off" must abandon the playing Group; "hue lights on" should not. Static at register time (no need for per-execution dynamism — YAGNI). Required (not optional with default) so every handler explicitly states its intent. |
| 8 | Registry collision policy: `register` throws | Two integrations both registering `"hue"` is a real bug to surface loudly at plugin enable, not a silent override. |
| 9 | Built-ins (`debug` today, `companion` later) register at app bootstrap with `source: 'core'`. Integrations register on plugin enable / unregister on disable, with `source: 'integration:${pluginId}'`. | Mirrors the existing inline-trigger pattern; same lifecycle, same plumbing. |
| 10 | Dispatcher is async (handlers may do API calls); failures from handler `execute` are caught and converted to error responses, with `onTriggerWhilePlaying = 'resume'` enforced on failure. | A buggy handler must not be able to kill the persona's reply. |
| 11 | Single interception point in `useConversationMode.ts`, before `controller.commit` | Mirrors the existing barge-state machine; no parallel STT path. |

---

## 5. Architecture

### 5.1 Module layout

```
frontend/src/features/voice-commands/
  types.ts            — CommandSpec, CommandResponse, DispatchResult
  normaliser.ts       — pure: normalise(text) → string[] tokens
  matcher.ts          — pure: match(tokens, registry) → {trigger, body} | null
  registry.ts         — Map<trigger, CommandSpec>; register / unregister / lookup; throws on collision
  responseChannel.ts  — respondToUser(response): v1 → toast; part 2 swaps body
  dispatcher.ts       — tryDispatchCommand(text): orchestrates the above
  handlers/
    debug.ts          — built-in: emits frontend event, returns success response
  index.ts            — public API: tryDispatchCommand, registerCommand, unregisterCommand, registerCoreBuiltins
  __tests__/
    normaliser.test.ts
    matcher.test.ts
    registry.test.ts
    dispatcher.test.ts
```

The module follows the project's "smaller, well-bounded units" principle: each file does one thing, no file is bigger than ~100 lines, pure logic stays free of React and side effects.

### 5.2 Data flow

```
STT result text
        ↓
useConversationMode.handleSttResult (around line 343)
        ↓
tryDispatchCommand(text)
        ├─ normalise(text) → tokens
        ├─ match(tokens, registry) → {trigger, body} | null
        │      └─ null → return { dispatched: false }
        ├─ registry.lookup(trigger) → handler
        ├─ try handler.execute(body) → CommandResponse
        │      catch → CommandResponse{level:'error',...}, force resume
        ├─ respondToUser(response) → useNotificationStore.addNotification (v1)
        └─ return { dispatched: true, onTriggerWhilePlaying }
        ↓
useConversationMode acts:
  not dispatched              → controller.commit(barge, text.trim())
  dispatched + 'abandon'      → controller.abandonAll()
  dispatched + 'resume'       → controller.resume(barge)
        ↓
publishBargeState()
```

---

## 6. Type contracts

```typescript
// types.ts

export interface CommandSpec {
  /** Single token: lowercase, no whitespace, no punctuation. e.g. 'debug', 'companion', 'hue'. */
  trigger: string

  /**
   * What to do with the active response Group when this command fires.
   * - 'abandon': cancel the paused Group entirely (e.g. 'companion off').
   * - 'resume': let the persona keep talking (e.g. 'hue lights on').
   * Required on every handler — explicit intent over implicit default.
   */
  onTriggerWhilePlaying: 'abandon' | 'resume'

  /** Source label for logs / debug. 'core' for built-ins, `integration:${id}` for plugins. */
  source: string

  /**
   * Execute the command. `body` is the normalised remainder after the trigger word
   * (may be ''). Async because handlers may do API calls. Throws are caught by the
   * dispatcher and converted to error responses.
   */
  execute: (body: string) => Promise<CommandResponse>
}

export interface CommandResponse {
  level: 'success' | 'info' | 'error'
  /** What the system-voice will say in part 2. v1 logs only, does not render. */
  spokenText: string
  /** What the toast displays in v1; persists as fallback in part 2. */
  displayText: string
}

export type DispatchResult =
  | { dispatched: false }
  | { dispatched: true; onTriggerWhilePlaying: 'abandon' | 'resume' }
```

---

## 7. Normalisation

```typescript
// normaliser.ts

export const LEADING_FILLERS: ReadonlySet<string> = new Set([
  'uh', 'um', 'uhm', 'hey', 'ok', 'okay', 'äh', 'ähm', 'also', 'naja',
])

const PUNCTUATION_PATTERN = /[.,;:!?…„"'']/gu

export function normalise(text: string): string[] {
  const lowered = text.toLowerCase()
  const stripped = lowered.replace(PUNCTUATION_PATTERN, ' ')
  const tokens = stripped.trim().split(/\s+/).filter(Boolean)
  let i = 0
  while (i < tokens.length && LEADING_FILLERS.has(tokens[i])) i += 1
  return tokens.slice(i)
}
```

Filler-stripping is greedy from the left until a non-filler token is hit ("uh um companion off" → strip both "uh" and "um", land on "companion"). The set lives next to the function so the wartung path is one file edit.

## 8. Matching

```typescript
// matcher.ts

export interface MatchResult {
  trigger: string
  body: string
}

export function match(tokens: string[], registry: Registry): MatchResult | null {
  if (tokens.length === 0) return null
  const trigger = tokens[0]
  if (!registry.has(trigger)) return null
  return { trigger, body: tokens.slice(1).join(' ') }
}
```

Word-boundary discipline is enforced for free by tokenisation: `"companionship"` is one token, never matches `"companion"`. No fuzzy logic, no substring search, no Levenshtein — exact key lookup only. Body may be the empty string (e.g. user just said `"debug"` without any payload) and is passed through to the handler verbatim.

## 9. Registry

```typescript
// registry.ts

const registry = new Map<string, CommandSpec>()

export function registerCommand(spec: CommandSpec): void {
  if (registry.has(spec.trigger)) {
    throw new Error(
      `Voice command trigger '${spec.trigger}' already registered (existing source: ${
        registry.get(spec.trigger)!.source
      }, attempted source: ${spec.source}).`,
    )
  }
  registry.set(spec.trigger, spec)
}

export function unregisterCommand(trigger: string): void {
  registry.delete(trigger)
}

export function lookupCommand(trigger: string): CommandSpec | undefined {
  return registry.get(trigger)
}

// matcher uses this; exposed for testability
export function hasCommand(trigger: string): boolean {
  return registry.has(trigger)
}
```

Throwing on collision is deliberate: when two integrations both want `"hue"`, this fails loudly at plugin enable rather than silently overriding. Surfacing this kind of bug at integration time is the point.

## 10. Response channel

```typescript
// responseChannel.ts (v1)
import { useNotificationStore } from '../../core/store/notificationStore'
import type { CommandResponse } from './types'

export function respondToUser(response: CommandResponse): void {
  console.debug('[VoiceCommand] response:', response)
  useNotificationStore.getState().addNotification({
    level: response.level,        // 'success' | 'info' | 'error' all valid in the store
    title: 'Voice command',
    message: response.displayText,
  })
}
```

The notification store accepts `'success' | 'info' | 'warning' | 'error'`, so all `CommandResponse.level` values pass through unchanged.

Part 2 will replace the body with: read user's system-voice setting → if set, look up `(voiceId, spokenText)` in the cache → on miss, synthesise + cache → play through a dedicated audio channel (overlays the persona, does not block her). On no system voice configured, fall back to the toast path above. **Interface stays untouched.**

## 11. Dispatcher

```typescript
// dispatcher.ts

export async function tryDispatchCommand(text: string): Promise<DispatchResult> {
  const tokens = normalise(text)
  const hit = match(tokens, /* registry singleton */)
  if (!hit) return { dispatched: false }

  const handler = lookupCommand(hit.trigger)!
  let response: CommandResponse
  try {
    response = await handler.execute(hit.body)
  } catch (err) {
    console.error(`[VoiceCommand] handler '${hit.trigger}' threw:`, err)
    response = {
      level: 'error',
      spokenText: 'Command failed.',
      displayText: `Command '${hit.trigger}' failed — see console for details.`,
    }
    respondToUser(response)
    return { dispatched: true, onTriggerWhilePlaying: 'resume' }
  }

  respondToUser(response)
  return { dispatched: true, onTriggerWhilePlaying: handler.onTriggerWhilePlaying }
}
```

On a handler throw the dispatcher forces `'resume'` — a buggy handler must not be allowed to abandon the active Group. Handlers that *want* to abandon on success do so via their static spec.

## 12. Controller integration

In `frontend/src/features/voice/hooks/useConversationMode.ts`, replace the existing branch around lines 343-347:

```typescript
// Existing:
//   if (result.text.trim() === '') {
//     controller.resume(barge)
//   } else {
//     controller.commit(barge, result.text.trim())
//   }

if (result.text.trim() === '') {
  controller.resume(barge)
} else {
  const dispatch = await tryDispatchCommand(result.text)
  if (dispatch.dispatched) {
    if (dispatch.onTriggerWhilePlaying === 'abandon') {
      controller.abandonAll()
    } else {
      controller.resume(barge)
    }
  } else {
    controller.commit(barge, result.text.trim())
  }
}
publishBargeState()
```

This is the single interception point. There is no other path; the dispatcher cannot be bypassed and cannot be invoked from anywhere else (`tryDispatchCommand` is callable from outside the hook, but in practice nothing else needs to).

## 13. Plugin lifecycle integration

Add an optional field to the integration plugin spec in `frontend/src/features/integrations/types.ts`:

```typescript
export interface IntegrationPlugin {
  // ... existing fields
  voiceCommands?: CommandSpec[]
}
```

In `frontend/src/features/integrations/pluginLifecycle.ts`:

- **On plugin enable:** for each `spec` in `plugin.voiceCommands ?? []`, call `registerCommand({ ...spec, source: \`integration:${plugin.id}\` })`. The `source` is overwritten by the lifecycle code so plugins cannot lie about their own origin.
- **On plugin disable:** for each, call `unregisterCommand(spec.trigger)`.

Built-ins follow a different lifecycle: `index.ts` exports `registerCoreBuiltins()` which is called once from the app bootstrap (alongside the existing inline-trigger and integration-store init). It registers `debugCommand` (and later `companion*`) with `source: 'core'`.

## 14. Built-in: `debug`

`handlers/debug.ts`:

```typescript
import { eventBus } from '../../../core/websocket/eventBus'
import type { CommandSpec, CommandResponse } from '../types'

export const debugCommand: CommandSpec = {
  trigger: 'debug',
  onTriggerWhilePlaying: 'resume',
  source: 'core',
  execute: async (body: string): Promise<CommandResponse> => {
    eventBus.emit({
      id: `voice-cmd-debug-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type: 'voice_command.debug',
      sequence: '0',
      scope: 'frontend',
      correlation_id: `voice-cmd-debug-${Date.now()}`,
      timestamp: new Date().toISOString(),
      payload: { body },
    })
    return {
      level: 'info',
      spokenText: 'Debug command received.',
      displayText: `Debug: '${body || '(empty)'}'`,
    }
  },
}
```

Topic naming convention for future per-command frontend events: `voice_command.<trigger>`. Not added to `shared/topics.py` — these are frontend-internal signals from a frontend dispatcher and do not cross the WebSocket boundary. If a future command needs a backend-side event, it gets a proper topic constant in `shared/topics.py` like everything else.

The consumer side is a tiny mounted-once component:

```tsx
// frontend/src/app/components/VoiceCommandDebugAlert.tsx
import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'

export function VoiceCommandDebugAlert(): null {
  useEffect(() => {
    const off = eventBus.on('voice_command.debug', (event) => {
      const body = (event.payload as { body?: string }).body ?? ''
      // Deliberately ugly — this is a debug affordance, not a UX feature.
      window.alert(`Voice debug command body: '${body || '(empty)'}'`)
    })
    return off
  }, [])
  return null
}
```

Mounted once near the app root.

## 15. Testing

### 15.1 Unit tests

Pure modules each get their own Vitest file under `__tests__/`:

- **`normaliser.test.ts`**
  - Empty string returns `[]`.
  - Plain text: `"Companion off"` → `['companion', 'off']`.
  - Trailing punctuation: `"Companion off."` → `['companion', 'off']`.
  - Inline punctuation: `"Companion, off."` → `['companion', 'off']`.
  - Multiple internal spaces: `"  companion    off  "` → `['companion', 'off']`.
  - Single leading filler: `"hey companion off"` → `['companion', 'off']`.
  - Multiple leading fillers: `"uh um hey companion off"` → `['companion', 'off']`.
  - Filler not at start is preserved: `"companion uh off"` → `['companion', 'uh', 'off']`.
  - Only fillers: `"uh um"` → `[]`.
  - Unicode punctuation: `"Companion „off"` → `['companion', 'off']`.

- **`matcher.test.ts`** (with a stub registry that contains `companion`):
  - `[]` → `null`.
  - `['unknown', 'foo']` → `null`.
  - `['companion', 'off']` → `{trigger: 'companion', body: 'off'}`.
  - `['companion']` → `{trigger: 'companion', body: ''}`.
  - `['companionship', 'is', 'great']` → `null` (token boundary).
  - `['companion', 'is', 'a', 'good', 'word']` → `{trigger: 'companion', body: 'is a good word'}`.

- **`registry.test.ts`**
  - `registerCommand` adds, `lookupCommand` returns it.
  - Second `registerCommand` with same trigger throws, error message includes both `source` values.
  - `unregisterCommand` removes; subsequent `lookupCommand` returns `undefined`.
  - `unregisterCommand` on unknown trigger is a no-op (does not throw).

- **`dispatcher.test.ts`** (with mocked registry, mocked `respondToUser`):
  - No-match → `{dispatched: false}`, `respondToUser` not called.
  - Successful execute → `respondToUser` called with handler's response, return matches handler's `onTriggerWhilePlaying`.
  - Handler throws → `respondToUser` called with error response, return forces `'resume'`.
  - Body extraction: handler receives the joined remainder verbatim.

### 15.2 Integration test

Extend `frontend/src/features/voice/hooks/__tests__/useConversationMode.holdRelease.test.tsx` (or new file) with one case:

- STT returns `"debug ping"` → `controller.commit` is **not** called; `controller.resume` is called instead; one toast notification is emitted.

### 15.3 Manual verification

Continuous voice on, conversation active:

1. Say `"debug hello world"` → `window.alert` pops with `Voice debug command body: 'hello world'`; toast shows `Debug: 'hello world'`.
2. While the persona is mid-sentence, say `"debug ping"` → persona keeps talking (resume); alert pops; toast shows.
3. Say just `"debug"` (no body) → alert shows `(empty)`; toast shows `Debug: '(empty)'`.
4. Say `"debugfoo"` (no space) → no command triggered; the utterance is sent to the LLM as a normal prompt.
5. Say `"uh debug test"` → filler stripped; alert pops with body `'test'`.
6. Say `"hey companionship is great"` → `companionship` is not a registered trigger; runs as a normal LLM prompt.
7. Open the browser console and confirm a `[VoiceCommand] response: {...}` debug log appears for every successful dispatch.

---

## 16. Out of scope and follow-ups

### Part 2 — System-voice + cache (next session)

See `devdocs/specs/_brief-voice-commands-part2-system-voice.md`. Replaces the body of `respondToUser` with a system-voice playback path; toast remains as fallback when the user has not configured a system voice. **Blocker for part 3.**

### Part 3 — Companion commands (after part 2)

Three concrete commands using the foundation:
- `companion off` — pause STT and TTS (mute mic + halt all playback).
- `companion on` — resume both.
- `companion status` — speak the current state through the system voice.

Will introduce additional concerns around the on/off state ("a little involved" per Chris during brainstorming) — defer the design to its own session once part 2 is in.

### Pre-existing code touched

- `useConversationMode.ts` — only the small commit/dispatch branch around lines 343-347.
- `integrations/types.ts` — one optional field added to the plugin spec.
- `integrations/pluginLifecycle.ts` — register/unregister calls in the existing enable/disable paths.

Nothing else changes. Existing inline-trigger machinery, response-task-group, barge controller, audio playback, settings — all untouched.
