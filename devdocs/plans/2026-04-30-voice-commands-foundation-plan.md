# Voice Commands Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Hard constraint for every dispatched subagent:** do NOT merge to master, do NOT push, do NOT switch branches. Implementation only — branch decisions stay with the orchestrator.

**Goal:** Build a continuous-voice-only command subsystem that bypasses the LLM, with one trivial built-in (`debug`) that proves the full pipeline. Foundation only — system-voice and companion commands ship in later sessions.

**Architecture:** New module `frontend/src/features/voice-commands/` with single-purpose files (types, normaliser, matcher, registry, dispatcher, response-channel, handlers, public index). Single STT-side interception in `useConversationMode.ts` before `controller.commit`. Plugin lifecycle integration via a new optional `voiceCommands?: CommandSpec[]` field on the existing `IntegrationPlugin` type. Toast-only response channel for v1; the interface is shaped so part 2 (system-voice + cache) only swaps the body of `respondToUser`.

**Tech Stack:** TypeScript / Vite / React, Vitest for unit and integration tests, existing zustand notification store, existing frontend `eventBus`.

**Spec:** `devdocs/specs/2026-04-30-voice-commands-foundation-design.md`

---

## File Structure

**To create:**
- `frontend/src/features/voice-commands/types.ts` — `CommandSpec`, `CommandResponse`, `DispatchResult`
- `frontend/src/features/voice-commands/normaliser.ts` — pure normalisation + filler stripping
- `frontend/src/features/voice-commands/registry.ts` — Map-backed registry with collision-throws
- `frontend/src/features/voice-commands/matcher.ts` — pure first-token-exact match
- `frontend/src/features/voice-commands/responseChannel.ts` — `respondToUser`; v1 → toast
- `frontend/src/features/voice-commands/dispatcher.ts` — orchestrator with try/catch
- `frontend/src/features/voice-commands/handlers/debug.ts` — single built-in
- `frontend/src/features/voice-commands/index.ts` — public API + `registerCoreBuiltins()`
- `frontend/src/features/voice-commands/__tests__/normaliser.test.ts`
- `frontend/src/features/voice-commands/__tests__/registry.test.ts`
- `frontend/src/features/voice-commands/__tests__/matcher.test.ts`
- `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts`
- `frontend/src/app/components/VoiceCommandDebugAlert.tsx`

**To modify:**
- `frontend/src/features/integrations/types.ts` — add optional `voiceCommands?` field on `IntegrationPlugin`
- `frontend/src/features/integrations/pluginLifecycle.ts` — register/unregister voice commands on plugin activate/deactivate
- `frontend/src/features/voice/hooks/useConversationMode.ts:343-347` — branch on `tryDispatchCommand` before `controller.commit`
- `frontend/src/App.tsx` — call `registerCoreBuiltins()` once + mount `<VoiceCommandDebugAlert />`

---

## Conventions

- Test command for a single file: `pnpm vitest run <relative path>` (cwd = `frontend/`)
- Test command for full frontend suite: `pnpm vitest run`
- Build verification: `pnpm run build` (cwd = `frontend/`) — runs `tsc -b && vite build` per `frontend/package.json`
- All commits use the existing repo style (imperative, free-form, no Conventional-Commits prefix)
- All file content is British English in code/comments

---

## Task 1: Types module

**Files:**
- Create: `frontend/src/features/voice-commands/types.ts`

This task creates the type contracts used by every other module in the feature. No tests — pure type declarations have no runtime behaviour.

- [ ] **Step 1: Create the types file**

```typescript
// frontend/src/features/voice-commands/types.ts

/**
 * Voice-command type contracts.
 *
 * The foundation supports continuous-voice-only commands that bypass the LLM
 * entirely. Handlers receive the normalised body (everything after the
 * trigger word) and return a structured response that the response channel
 * renders — today as a toast, in part 2 as a cached system-voice utterance
 * with toast fallback.
 */

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

- [ ] **Step 2: Verify TypeScript still compiles**

Run from `frontend/`:
```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice-commands/types.ts
git commit -m "Add voice-commands type contracts (CommandSpec, CommandResponse, DispatchResult)"
```

---

## Task 2: Normaliser module (TDD)

**Files:**
- Create: `frontend/src/features/voice-commands/normaliser.ts`
- Test: `frontend/src/features/voice-commands/__tests__/normaliser.test.ts`

Pure function: text → token array, with lowercase + punctuation stripping + leading-filler removal.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/features/voice-commands/__tests__/normaliser.test.ts
import { describe, it, expect } from 'vitest'
import { normalise } from '../normaliser'

describe('normalise', () => {
  it('returns [] for empty string', () => {
    expect(normalise('')).toEqual([])
  })

  it('returns [] for whitespace-only string', () => {
    expect(normalise('   \t\n  ')).toEqual([])
  })

  it('lowercases and tokenises plain text', () => {
    expect(normalise('Companion off')).toEqual(['companion', 'off'])
  })

  it('strips trailing punctuation', () => {
    expect(normalise('Companion off.')).toEqual(['companion', 'off'])
  })

  it('strips inline punctuation', () => {
    expect(normalise('Companion, off.')).toEqual(['companion', 'off'])
  })

  it('collapses multiple internal spaces', () => {
    expect(normalise('  companion    off  ')).toEqual(['companion', 'off'])
  })

  it('strips a single leading filler', () => {
    expect(normalise('hey companion off')).toEqual(['companion', 'off'])
  })

  it('strips multiple leading fillers greedily', () => {
    expect(normalise('uh um hey companion off')).toEqual(['companion', 'off'])
  })

  it('preserves filler tokens that are not at the start', () => {
    expect(normalise('companion uh off')).toEqual(['companion', 'uh', 'off'])
  })

  it('returns [] when all tokens are fillers', () => {
    expect(normalise('uh um')).toEqual([])
  })

  it('strips German fillers (äh, ähm, also, naja)', () => {
    expect(normalise('äh companion off')).toEqual(['companion', 'off'])
    expect(normalise('ähm companion')).toEqual(['companion'])
    expect(normalise('also naja companion')).toEqual(['companion'])
  })

  it('strips Unicode punctuation (German quotes, ellipsis)', () => {
    expect(normalise('Companion „off…')).toEqual(['companion', 'off'])
  })

  it('handles a body that is just the trigger word', () => {
    expect(normalise('Debug')).toEqual(['debug'])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run from `frontend/`:
```bash
pnpm vitest run src/features/voice-commands/__tests__/normaliser.test.ts
```
Expected: FAIL — module `../normaliser` not found.

- [ ] **Step 3: Write the implementation**

```typescript
// frontend/src/features/voice-commands/normaliser.ts

/**
 * Normalise a raw STT result into a token array suitable for command matching.
 *
 * Pipeline:
 *   1. lowercase
 *   2. replace punctuation characters with spaces
 *   3. trim outer whitespace, split on whitespace, drop empty tokens
 *   4. greedily strip leading filler tokens (one at a time, until a non-filler is hit)
 *
 * Returns an empty array if normalisation leaves nothing — caller should
 * treat this as a no-match (no trigger possible).
 */

export const LEADING_FILLERS: ReadonlySet<string> = new Set([
  'uh',
  'um',
  'uhm',
  'hey',
  'ok',
  'okay',
  'äh',
  'ähm',
  'also',
  'naja',
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

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
pnpm vitest run src/features/voice-commands/__tests__/normaliser.test.ts
```
Expected: PASS — all 13 cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice-commands/normaliser.ts frontend/src/features/voice-commands/__tests__/normaliser.test.ts
git commit -m "Add voice-command normaliser with filler stripping and tests"
```

---

## Task 3: Registry module (TDD)

**Files:**
- Create: `frontend/src/features/voice-commands/registry.ts`
- Test: `frontend/src/features/voice-commands/__tests__/registry.test.ts`

Map-backed registry with collision-throws. Module-level singleton plus a test-only reset hook (mirrors the `_resetPluginRegistry` pattern used in `frontend/src/features/integrations/registry.ts`).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/features/voice-commands/__tests__/registry.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import {
  registerCommand,
  unregisterCommand,
  lookupCommand,
  hasCommand,
  _resetRegistry,
} from '../registry'
import type { CommandSpec } from '../types'

function makeSpec(overrides: Partial<CommandSpec> = {}): CommandSpec {
  return {
    trigger: 'foo',
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: async () => ({
      level: 'info',
      spokenText: '',
      displayText: '',
    }),
    ...overrides,
  }
}

describe('registry', () => {
  beforeEach(() => {
    _resetRegistry()
  })

  it('registers and looks up a command', () => {
    const spec = makeSpec()
    registerCommand(spec)
    expect(lookupCommand('foo')).toBe(spec)
    expect(hasCommand('foo')).toBe(true)
  })

  it('throws on collision with both source labels in the message', () => {
    const a = makeSpec({ source: 'core' })
    const b = makeSpec({ source: 'integration:hue' })
    registerCommand(a)
    expect(() => registerCommand(b)).toThrow(/already registered/)
    expect(() => registerCommand(b)).toThrow(/core/)
    expect(() => registerCommand(b)).toThrow(/integration:hue/)
  })

  it('unregister removes the command', () => {
    registerCommand(makeSpec())
    unregisterCommand('foo')
    expect(lookupCommand('foo')).toBeUndefined()
    expect(hasCommand('foo')).toBe(false)
  })

  it('unregister on unknown trigger is a no-op', () => {
    expect(() => unregisterCommand('does-not-exist')).not.toThrow()
  })

  it('hasCommand returns false for unknown triggers', () => {
    expect(hasCommand('nope')).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm vitest run src/features/voice-commands/__tests__/registry.test.ts
```
Expected: FAIL — module `../registry` not found.

- [ ] **Step 3: Write the implementation**

```typescript
// frontend/src/features/voice-commands/registry.ts

import type { CommandSpec } from './types'

const registry = new Map<string, CommandSpec>()

export function registerCommand(spec: CommandSpec): void {
  const existing = registry.get(spec.trigger)
  if (existing) {
    throw new Error(
      `Voice command trigger '${spec.trigger}' already registered ` +
        `(existing source: ${existing.source}, attempted source: ${spec.source}).`,
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

export function hasCommand(trigger: string): boolean {
  return registry.has(trigger)
}

/** FOR TESTING ONLY — resets the singleton registry. Do not call in production code. */
export function _resetRegistry(): void {
  registry.clear()
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm vitest run src/features/voice-commands/__tests__/registry.test.ts
```
Expected: PASS — 5 cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice-commands/registry.ts frontend/src/features/voice-commands/__tests__/registry.test.ts
git commit -m "Add voice-command registry with collision-throws and reset hook"
```

---

## Task 4: Matcher module (TDD)

**Files:**
- Create: `frontend/src/features/voice-commands/matcher.ts`
- Test: `frontend/src/features/voice-commands/__tests__/matcher.test.ts`

Pure function over normalised tokens. Uses the registry's `hasCommand` for the lookup decision.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/features/voice-commands/__tests__/matcher.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { match } from '../matcher'
import { registerCommand, _resetRegistry } from '../registry'
import type { CommandSpec } from '../types'

function makeSpec(trigger: string): CommandSpec {
  return {
    trigger,
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: async () => ({ level: 'info', spokenText: '', displayText: '' }),
  }
}

describe('match', () => {
  beforeEach(() => {
    _resetRegistry()
    registerCommand(makeSpec('companion'))
    registerCommand(makeSpec('debug'))
  })

  it('returns null for an empty token list', () => {
    expect(match([])).toBeNull()
  })

  it('returns null when first token is not a registered trigger', () => {
    expect(match(['unknown', 'foo'])).toBeNull()
  })

  it('returns trigger and joined body when first token matches', () => {
    expect(match(['companion', 'off'])).toEqual({
      trigger: 'companion',
      body: 'off',
    })
  })

  it('returns empty body when only the trigger word is present', () => {
    expect(match(['companion'])).toEqual({ trigger: 'companion', body: '' })
  })

  it('does NOT match a longer token that starts with the trigger', () => {
    expect(match(['companionship', 'is', 'great'])).toBeNull()
  })

  it('joins all body tokens with a single space', () => {
    expect(match(['companion', 'is', 'a', 'good', 'word'])).toEqual({
      trigger: 'companion',
      body: 'is a good word',
    })
  })

  it('matches the debug trigger', () => {
    expect(match(['debug', 'ping'])).toEqual({ trigger: 'debug', body: 'ping' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm vitest run src/features/voice-commands/__tests__/matcher.test.ts
```
Expected: FAIL — module `../matcher` not found.

- [ ] **Step 3: Write the implementation**

```typescript
// frontend/src/features/voice-commands/matcher.ts

import { hasCommand } from './registry'

export interface MatchResult {
  trigger: string
  body: string
}

/**
 * Return the trigger + body if `tokens[0]` is a registered command, else null.
 *
 * Tokens are assumed to be the output of `normalise()` — already lowercased,
 * punctuation-free, with leading fillers stripped. Word-boundary discipline
 * is enforced for free by tokenisation: 'companionship' is a single token
 * and never matches 'companion'.
 */
export function match(tokens: string[]): MatchResult | null {
  if (tokens.length === 0) return null
  const trigger = tokens[0]
  if (!hasCommand(trigger)) return null
  return { trigger, body: tokens.slice(1).join(' ') }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm vitest run src/features/voice-commands/__tests__/matcher.test.ts
```
Expected: PASS — 7 cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice-commands/matcher.ts frontend/src/features/voice-commands/__tests__/matcher.test.ts
git commit -m "Add voice-command matcher (first-token exact match against registry)"
```

---

## Task 5: Response channel (toast-only v1)

**Files:**
- Create: `frontend/src/features/voice-commands/responseChannel.ts`

Slim implementation that pushes through the existing `useNotificationStore`. Intentionally tiny — part 2 swaps the body in.

- [ ] **Step 1: Create the response channel**

```typescript
// frontend/src/features/voice-commands/responseChannel.ts

/**
 * respondToUser — render a CommandResponse to the user.
 *
 * v1 implementation: log to console, push a toast through the existing
 * notification store. Part 2 will replace the body with system-voice
 * playback (cached) and fall back to this toast path when no system voice
 * is configured. The function signature is the stable contract that
 * handlers depend on across both versions — do NOT change it.
 */

import { useNotificationStore } from '../../core/store/notificationStore'
import type { CommandResponse } from './types'

export function respondToUser(response: CommandResponse): void {
  console.debug('[VoiceCommand] response:', response)
  useNotificationStore.getState().addNotification({
    level: response.level,
    title: 'Voice command',
    message: response.displayText,
  })
}
```

- [ ] **Step 2: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors. (If `useNotificationStore` import path resolves, this is good — that path was verified during spec drafting.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice-commands/responseChannel.ts
git commit -m "Add voice-command response channel (toast-only for v1)"
```

---

## Task 6: Dispatcher (TDD)

**Files:**
- Create: `frontend/src/features/voice-commands/dispatcher.ts`
- Test: `frontend/src/features/voice-commands/__tests__/dispatcher.test.ts`

Orchestrates normalise → match → execute → respond. Tests mock the response channel and use the real registry/normaliser/matcher (they are pure and already proven).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/features/voice-commands/__tests__/dispatcher.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { tryDispatchCommand } from '../dispatcher'
import { registerCommand, _resetRegistry } from '../registry'
import type { CommandSpec, CommandResponse } from '../types'

vi.mock('../responseChannel', () => ({
  respondToUser: vi.fn(),
}))

import { respondToUser } from '../responseChannel'
const respondMock = vi.mocked(respondToUser)

function makeSpec(overrides: Partial<CommandSpec> = {}): CommandSpec {
  return {
    trigger: 'demo',
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: vi.fn(async (): Promise<CommandResponse> => ({
      level: 'success',
      spokenText: 'ok',
      displayText: 'ok',
    })),
    ...overrides,
  }
}

describe('tryDispatchCommand', () => {
  beforeEach(() => {
    _resetRegistry()
    respondMock.mockReset()
  })

  it('returns {dispatched:false} and does not call respondToUser when no trigger matches', async () => {
    const result = await tryDispatchCommand('hello world')
    expect(result).toEqual({ dispatched: false })
    expect(respondMock).not.toHaveBeenCalled()
  })

  it('returns {dispatched:false} for empty input', async () => {
    const result = await tryDispatchCommand('')
    expect(result).toEqual({ dispatched: false })
    expect(respondMock).not.toHaveBeenCalled()
  })

  it('returns {dispatched:false} when input is only fillers', async () => {
    const result = await tryDispatchCommand('uh um')
    expect(result).toEqual({ dispatched: false })
    expect(respondMock).not.toHaveBeenCalled()
  })

  it('executes the handler with the joined body and forwards the response', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    const result = await tryDispatchCommand('demo hello world')
    expect(spec.execute).toHaveBeenCalledWith('hello world')
    expect(respondMock).toHaveBeenCalledWith({
      level: 'success',
      spokenText: 'ok',
      displayText: 'ok',
    })
    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'resume' })
  })

  it('passes empty body when only the trigger word was spoken', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    await tryDispatchCommand('demo')
    expect(spec.execute).toHaveBeenCalledWith('')
  })

  it('returns onTriggerWhilePlaying:abandon when the handler is configured that way', async () => {
    registerCommand(makeSpec({ onTriggerWhilePlaying: 'abandon' }))
    const result = await tryDispatchCommand('demo off')
    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'abandon' })
  })

  it('catches handler throws, emits an error response, forces resume', async () => {
    const spec = makeSpec({
      onTriggerWhilePlaying: 'abandon',
      execute: vi.fn(async () => {
        throw new Error('boom')
      }),
    })
    registerCommand(spec)
    const result = await tryDispatchCommand('demo crash')
    expect(respondMock).toHaveBeenCalledWith(
      expect.objectContaining({ level: 'error' }),
    )
    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'resume' })
  })

  it('strips leading fillers before matching', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    await tryDispatchCommand('hey demo  do something')
    expect(spec.execute).toHaveBeenCalledWith('do something')
  })

  it('strips punctuation before matching', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    await tryDispatchCommand('Demo, off.')
    expect(spec.execute).toHaveBeenCalledWith('off')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pnpm vitest run src/features/voice-commands/__tests__/dispatcher.test.ts
```
Expected: FAIL — module `../dispatcher` not found.

- [ ] **Step 3: Write the implementation**

```typescript
// frontend/src/features/voice-commands/dispatcher.ts

import { normalise } from './normaliser'
import { match } from './matcher'
import { lookupCommand } from './registry'
import { respondToUser } from './responseChannel'
import type { CommandResponse, DispatchResult } from './types'

/**
 * Attempt to dispatch the STT-result text as a voice command.
 *
 * Returns `{dispatched:false}` when the text does not match any registered
 * trigger — caller should treat the text as a normal LLM prompt.
 *
 * On a match, runs the handler, renders the response, and returns the
 * `onTriggerWhilePlaying` flag so the caller can decide what to do with the
 * paused response Group. Handler throws are caught and converted to error
 * responses, with `onTriggerWhilePlaying` forced to 'resume' so a buggy
 * handler cannot kill the persona's reply.
 */
export async function tryDispatchCommand(text: string): Promise<DispatchResult> {
  const tokens = normalise(text)
  const hit = match(tokens)
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

- [ ] **Step 4: Run test to verify it passes**

```bash
pnpm vitest run src/features/voice-commands/__tests__/dispatcher.test.ts
```
Expected: PASS — 9 cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice-commands/dispatcher.ts frontend/src/features/voice-commands/__tests__/dispatcher.test.ts
git commit -m "Add voice-command dispatcher with handler-throw containment"
```

---

## Task 7: Debug built-in handler

**Files:**
- Create: `frontend/src/features/voice-commands/handlers/debug.ts`

The single built-in. Emits a frontend-internal `voice_command.debug` event on the existing `eventBus`. Topic naming convention `voice_command.<trigger>` is documented in the spec; not added to `shared/topics.py` because this signal does not cross the WS boundary.

- [ ] **Step 1: Create the handler**

```typescript
// frontend/src/features/voice-commands/handlers/debug.ts

import { eventBus } from '../../../core/websocket/eventBus'
import type { CommandSpec, CommandResponse } from '../types'

/**
 * Built-in debug command. Emits a frontend-internal event carrying the
 * normalised body; a small mounted component pops a window.alert in
 * response. Proves the full pipeline end-to-end with the smallest
 * possible consumer.
 *
 * Topic naming convention for future per-command frontend events:
 * 'voice_command.<trigger>'. Frontend-only — not added to
 * shared/topics.py because this signal does not cross the WS boundary.
 */
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

- [ ] **Step 2: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice-commands/handlers/debug.ts
git commit -m "Add debug voice-command handler emitting frontend event"
```

---

## Task 8: Public index + registerCoreBuiltins

**Files:**
- Create: `frontend/src/features/voice-commands/index.ts`

The single public API surface for the module. `App.tsx` imports `registerCoreBuiltins` and calls it once at app start; `useConversationMode` imports `tryDispatchCommand`; `pluginLifecycle` imports `registerCommand` and `unregisterCommand`. Internal files (`registry.ts`, `dispatcher.ts`, etc.) are not imported from outside the module.

- [ ] **Step 1: Create the public index**

```typescript
// frontend/src/features/voice-commands/index.ts

/**
 * Public API of the voice-commands module.
 *
 * External callers (App bootstrap, useConversationMode, pluginLifecycle)
 * import from this file. Internal files (registry, dispatcher, matcher,
 * normaliser, responseChannel, handlers/*) are private — do not import
 * them directly from outside this module.
 */

import { registerCommand } from './registry'
import { debugCommand } from './handlers/debug'

export { tryDispatchCommand } from './dispatcher'
export { registerCommand, unregisterCommand } from './registry'
export type { CommandSpec, CommandResponse, DispatchResult } from './types'

/**
 * Register all core built-in voice commands. Call once at app bootstrap,
 * after auth gate. Idempotency is the caller's responsibility — calling
 * this twice will throw on collision (which is intentional: a double-init
 * is a real bug).
 */
export function registerCoreBuiltins(): void {
  registerCommand(debugCommand)
}
```

- [ ] **Step 2: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice-commands/index.ts
git commit -m "Add voice-commands public index (tryDispatch, register/unregister, registerCoreBuiltins)"
```

---

## Task 9: Debug alert component (consumer)

**Files:**
- Create: `frontend/src/app/components/VoiceCommandDebugAlert.tsx`

Tiny component, mounted once at app root. Subscribes to `voice_command.debug` and pops `window.alert` for each event. Returns `null` (no DOM).

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/app/components/VoiceCommandDebugAlert.tsx

import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'

/**
 * Mount-once consumer for the debug voice command's event.
 *
 * Deliberately ugly — this is a debug affordance to prove the voice-command
 * pipeline end-to-end, not a UX feature. Replace or remove when the
 * pipeline is exercised by real commands (companion, hue, …).
 */
export function VoiceCommandDebugAlert(): null {
  useEffect(() => {
    const off = eventBus.on('voice_command.debug', (event) => {
      const body = (event.payload as { body?: string }).body ?? ''
      window.alert(`Voice debug command body: '${body || '(empty)'}'`)
    })
    return off
  }, [])
  return null
}
```

- [ ] **Step 2: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/VoiceCommandDebugAlert.tsx
git commit -m "Add VoiceCommandDebugAlert mount-once consumer for debug pipeline"
```

---

## Task 10: Plugin lifecycle integration

**Files:**
- Modify: `frontend/src/features/integrations/types.ts:106-137` (the `IntegrationPlugin` interface)
- Modify: `frontend/src/features/integrations/pluginLifecycle.ts` (the `reconcileOne` function)

Add the optional `voiceCommands` field to the plugin spec, then register/unregister them in lock-step with the existing `onActivate`/`onDeactivate` callbacks. The plugin lifecycle code overwrites `source` so plugins cannot lie about their origin.

- [ ] **Step 1: Read the current `IntegrationPlugin` interface**

Read `frontend/src/features/integrations/types.ts` lines 100-150 to confirm the current shape (it should match the spec — fields are `id`, `executeTag`, `executeTool`, `healthCheck`, `emergencyStop`, `ConfigComponent`, `ExtraConfigComponent`, `getPersonaConfigOptions`, `onActivate`, `onDeactivate`).

- [ ] **Step 2: Add the `voiceCommands` field**

In `frontend/src/features/integrations/types.ts`, add an `import type { CommandSpec }` near the other type imports, and add a new field to `IntegrationPlugin` after `onDeactivate`:

```typescript
// at the top of the file, alongside existing imports:
import type { CommandSpec } from '../voice-commands'
```

Then within `interface IntegrationPlugin`, append the new optional field (after the existing `onDeactivate?(): void` line):

```typescript
  /**
   * Voice commands this integration provides. Registered when the plugin
   * activates (with source `integration:${id}`) and unregistered when it
   * deactivates. The lifecycle code overwrites the `source` field so
   * plugins cannot misrepresent their origin.
   */
  voiceCommands?: CommandSpec[]
```

- [ ] **Step 3: Wire register/unregister in `reconcileOne`**

In `frontend/src/features/integrations/pluginLifecycle.ts`, add the import near the top alongside the existing imports:

```typescript
import { registerCommand, unregisterCommand } from '../voice-commands'
```

Replace the inside of the `if (desired === 'active') { ... } else { ... }` block in `reconcileOne` (currently calls only `plugin.onActivate?.()` / `plugin.onDeactivate?.()`):

```typescript
  if (desired === 'active') {
    plugin.onActivate?.()
    for (const spec of plugin.voiceCommands ?? []) {
      registerCommand({ ...spec, source: `integration:${integrationId}` })
    }
  } else {
    plugin.onDeactivate?.()
    for (const spec of plugin.voiceCommands ?? []) {
      unregisterCommand(spec.trigger)
    }
  }
```

- [ ] **Step 4: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors. (If a circular import error appears between `voice-commands` and `integrations`, double-check that `voice-commands/index.ts` only re-exports types from `./types` and does not import anything from `integrations`. The dependency direction is `integrations → voice-commands`, never the other way.)

- [ ] **Step 5: Run the existing pluginLifecycle tests if any exist**

```bash
pnpm vitest run src/features/integrations
```
Expected: all existing tests pass. (No new tests in this task — the lifecycle wiring is exercised end-to-end by the manual verification step in Task 13.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/integrations/types.ts frontend/src/features/integrations/pluginLifecycle.ts
git commit -m "Wire voice-command register/unregister into plugin lifecycle (activate/deactivate)"
```

---

## Task 11: useConversationMode interception

**Files:**
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts:343-347` (the STT-result branch inside `transcribeAndSend`)

Single insertion point. Replace the existing `if (empty) resume; else commit` branch with `if (empty) resume; else { dispatch attempt; act on result }`.

- [ ] **Step 1: Read the current branch to confirm exact lines**

Read `frontend/src/features/voice/hooks/useConversationMode.ts` around lines 340-350. The current code is:

```typescript
    if (result.text.trim() === '') {
      controller.resume(barge)
    } else {
      controller.commit(barge, result.text.trim())
    }
    publishBargeState()
```

(If the line numbers have drifted, search for `controller.commit(barge, result.text.trim())` to find the right block.)

- [ ] **Step 2: Add the import at the top of the file**

Append to the existing imports section:

```typescript
import { tryDispatchCommand } from '../../voice-commands'
```

- [ ] **Step 3: Replace the branch with the dispatcher-aware version**

Replace the four-line branch above with:

```typescript
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

The enclosing function (`transcribeAndSend`, declared `async` at line 278) already supports `await`, so no signature change is needed.

- [ ] **Step 4: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 5: Run existing useConversationMode tests to confirm nothing regresses**

```bash
pnpm vitest run src/features/voice/hooks/__tests__
```
Expected: all existing tests pass. The dispatcher returns `{dispatched:false}` for any text not matching a registered trigger, so the existing `commit` path runs unchanged for normal prompts (and the test fixtures don't register any triggers).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/hooks/useConversationMode.ts
git commit -m "Wire voice-command dispatcher into useConversationMode STT-result path"
```

---

## Task 12: App.tsx wiring

**Files:**
- Modify: `frontend/src/App.tsx` (the bootstrap `useEffect` in `AppRoutes` and the JSX returned from `AppRoutes`)

Two changes: call `registerCoreBuiltins()` once when the user is authenticated (alongside the existing init calls), and mount `<VoiceCommandDebugAlert />` as a sibling of `<ScreenEffectsOverlay />`.

- [ ] **Step 1: Add the imports at the top of `App.tsx`**

Append to the existing imports:

```typescript
import { registerCoreBuiltins } from "./features/voice-commands"
import { VoiceCommandDebugAlert } from "./app/components/VoiceCommandDebugAlert"
```

- [ ] **Step 2: Call `registerCoreBuiltins` in the bootstrap effect**

Locate the `useEffect` block in `AppRoutes` (currently at lines 82-95). Add the call **once** before any of the existing register calls. The block currently looks like:

```typescript
  useEffect(() => {
    if (!isAuthenticated) return

    const unregisterClientTool = registerClientToolHandler()
    const unregisterSecrets = registerSecretsEventHandler()
    const unregisterIntegrations = registerIntegrationsEventHandler()
    const cleanupPluginLifecycle = initPluginLifecycle()
    return () => {
      unregisterClientTool()
      unregisterSecrets()
      unregisterIntegrations()
      cleanupPluginLifecycle()
    }
  }, [isAuthenticated])
```

Change it to:

```typescript
  useEffect(() => {
    if (!isAuthenticated) return

    registerCoreBuiltins()
    const unregisterClientTool = registerClientToolHandler()
    const unregisterSecrets = registerSecretsEventHandler()
    const unregisterIntegrations = registerIntegrationsEventHandler()
    const cleanupPluginLifecycle = initPluginLifecycle()
    return () => {
      unregisterClientTool()
      unregisterSecrets()
      unregisterIntegrations()
      cleanupPluginLifecycle()
    }
  }, [isAuthenticated])
```

Note: `registerCoreBuiltins` has no cleanup counterpart. The registry survives across logout — this is fine because logout does not unmount the App component. If a future requirement adds a logout-side teardown (e.g. for hot-reload or test isolation), add an `unregisterCommand('debug')` helper next to `registerCoreBuiltins` and call it from the cleanup. Not needed today.

- [ ] **Step 3: Mount the debug alert component**

Locate the JSX returned from `AppRoutes` (currently lines 99-145). The existing `<ScreenEffectsOverlay />` is rendered as a sibling of `<Routes>` near the bottom. Add `<VoiceCommandDebugAlert />` next to it:

```tsx
      </Routes>
      <ScreenEffectsOverlay />
      <VoiceCommandDebugAlert />
    </>
```

- [ ] **Step 4: Verify TypeScript still compiles**

```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 5: Run the full test suite**

```bash
pnpm vitest run
```
Expected: all tests pass (including the four new test files from Tasks 2/3/4/6 and the unchanged existing suite).

- [ ] **Step 6: Run a clean production build**

```bash
pnpm run build
```
Expected: `tsc -b` clean, `vite build` clean, no TypeScript errors. (Per memory `feedback_frontend_build_check`, `pnpm run build` catches stricter type errors than `pnpm tsc --noEmit`.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "Bootstrap voice-command core builtins and mount debug alert"
```

---

## Task 13: Manual verification

This task is run by the orchestrator (Chris), not a subagent. The subagent that completes Task 12 hands control back; the orchestrator opens the app and walks through these scenarios.

**Goal:** prove the foundation pipeline end-to-end on a real device with continuous voice mode active.

- [ ] **Step 1: Start the dev server**

From `frontend/`:
```bash
pnpm dev
```
Open the app in the browser, log in, navigate to a chat with a configured persona that supports continuous voice.

- [ ] **Step 2: Enable continuous voice and run the verification checklist**

For each item: confirm the expected outcome before moving on. If anything fails, capture the browser console output and note which step.

1. Say `"debug hello world"` → `window.alert` pops with `Voice debug command body: 'hello world'`; toast shows `Debug: 'hello world'`.
2. While the persona is mid-sentence, say `"debug ping"` → persona keeps talking (resume); alert pops; toast shows.
3. Say just `"debug"` (no body) → alert shows `(empty)`; toast shows `Debug: '(empty)'`.
4. Say `"debugfoo"` (no space) → no command triggered; the utterance is sent to the LLM as a normal prompt.
5. Say `"uh debug test"` → filler stripped; alert pops with body `'test'`.
6. Say `"hey companionship is great"` → not a registered trigger; runs as a normal LLM prompt.
7. Open the browser console and confirm a `[VoiceCommand] response: {...}` debug log appears for every successful dispatch.

- [ ] **Step 3: Verify nothing regressed in the normal voice path**

Have a normal conversation (no command triggers) — the persona should respond as before, with no toasts and no console noise from the voice-commands module beyond a single `respondToUser` log on each dispatch (which should not happen for normal prompts).

- [ ] **Step 4: Sign off**

If all manual checks pass, the foundation is complete. The branch is ready to merge to master per the project's "merge to master after implementation" default.

---

## Self-Review Notes

Spec coverage check (run after writing the plan):

- §5 Architecture / module layout → Tasks 1-9 create every file listed.
- §6 Type contracts → Task 1.
- §7 Normalisation → Task 2 (with all rules covered in tests).
- §8 Matching → Task 4 (with `companionship` boundary case in tests).
- §9 Registry → Task 3 (with collision-throw and reset hook).
- §10 Response channel → Task 5 (toast-only); Task 6 verifies dispatcher calls it.
- §11 Dispatcher → Task 6 (with handler-throw containment in tests).
- §12 Controller integration → Task 11.
- §13 Plugin lifecycle integration → Task 10.
- §14 Built-in: debug → Task 7 (handler) + Task 9 (consumer) + Task 12 (mount).
- §15 Testing → unit tests in Tasks 2/3/4/6; integration coverage by existing useConversationMode tests in Task 11; manual verification in Task 13.
- §16 Out of scope → no tasks (correctly).

No placeholders. Type names consistent across tasks (`CommandSpec`, `CommandResponse`, `DispatchResult`, `MatchResult`, `tryDispatchCommand`, `registerCommand`, `unregisterCommand`, `lookupCommand`, `hasCommand`, `_resetRegistry`, `respondToUser`, `normalise`, `match`, `debugCommand`, `registerCoreBuiltins`, `VoiceCommandDebugAlert`).
