# Screen Effects Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `screen_effect` integration that consumes the existing inline-trigger foundation, ships `rising_emojis` as the first effect, defaults on for every user, and is structured so further effects (background overlays, viewport shake) can be added by dropping in one effect file plus one component.

**Architecture:** Single integration registered in the backend with `default_enabled=True`, `assignable=False`. Frontend plugin uses a small command→effect-fn map dispatcher. A globally-mounted overlay component subscribes to `Topics.INTEGRATION_INLINE_TRIGGER`, filters by `integration_id === 'screen_effect'`, and dispatches to a per-effect React component (`RisingEmojisEffect`). Random animation parameters live only inside the effect component so the live-vs-persisted pill equivalence invariant holds.

**Tech Stack:** Python 3 / FastAPI (backend metadata only — no runtime work), React + TypeScript + Vitest (frontend), `Intl.Segmenter` for grapheme-correct emoji parsing, plain DOM + CSS keyframe animation for the rendering layer.

**Spec:** `devdocs/specs/2026-04-30-screen-effects-integration-design.md`

**Subagent constraints (apply to every dispatch):**
- Do NOT merge to master, do NOT push, do NOT switch branches.
- Frontend build verification: `pnpm run build` (NOT just `pnpm tsc --noEmit`).
- For backend tests: simple module import / pytest assertion is fine; do not run the "full backend suite" without the standard MongoDB-test exclusion list.
- British English in all code, comments, prompt strings, commit messages.

---

## File Map

**Created:**
- `backend/modules/integrations/_screen_effects_prompt.py`
- `backend/tests/modules/integrations/__init__.py` (if directory does not exist yet)
- `backend/tests/modules/integrations/test_screen_effect_definition.py`
- `frontend/src/features/integrations/plugins/screen_effects/index.ts`
- `frontend/src/features/integrations/plugins/screen_effects/tags.ts`
- `frontend/src/features/integrations/plugins/screen_effects/effects/risingEmojis.ts`
- `frontend/src/features/integrations/plugins/screen_effects/overlay/ScreenEffectsOverlay.tsx`
- `frontend/src/features/integrations/plugins/screen_effects/overlay/RisingEmojisEffect.tsx`
- `frontend/src/features/integrations/plugins/screen_effects/__tests__/risingEmojis.test.ts`
- `frontend/src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts`
- `frontend/src/features/integrations/plugins/screen_effects/__tests__/RisingEmojisEffect.smoke.test.tsx`

**Modified:**
- `backend/modules/integrations/_registry.py` — append `register(...)` call inside `_register_builtins()`.
- `frontend/src/App.tsx` — add side-effect plugin import + mount `<ScreenEffectsOverlay />`.
- `frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts` — add a screen_effect case.

---

### Task 1: Backend prompt module + registration

**Files:**
- Create: `backend/modules/integrations/_screen_effects_prompt.py`
- Modify: `backend/modules/integrations/_registry.py` (append a `register(...)` call inside `_register_builtins()`)
- Create: `backend/tests/modules/integrations/__init__.py` (empty file, only if the directory does not yet exist)
- Create: `backend/tests/modules/integrations/test_screen_effect_definition.py`

**Background:** All existing integration definitions sit inside `_register_builtins()` in `_registry.py`. The helper `register(...)` is already in place. Each definition's prompt-template constant lives in a sibling `_*_prompt.py` for readability. We follow the same convention.

- [ ] **Step 1: Create the prompt module**

Write `backend/modules/integrations/_screen_effects_prompt.py`:

```python
"""System prompt extension injected for the ``screen_effect`` integration.

Kept in its own module so the (long) string lives outside the registry file
and can be edited without diff churn on the registration call.
"""

SCREEN_EFFECT_PROMPT = '''<screeneffects priority="normal">
You may emit small visual flourishes inline using the markup:

  <screen_effect rising_emojis 💖 🤘 🔥>

Available effects:
  - rising_emojis EMOJI [EMOJI ...] — a gentle upward shower of the given
    emojis (1..5), drifting and varying in size. Pass between 1 and 5
    distinct emojis.

Use sparingly — once per response at most, and only when it genuinely fits
the moment (a celebration, a flirt, a punchline). The user sees a small
monospace pill in chat at the spot where the tag appeared, and the effect
plays over the whole screen briefly. Effects are silent and never carry
prose meaning — your words still need to do the talking.
</screeneffects>'''
```

- [ ] **Step 2: Register the integration**

In `backend/modules/integrations/_registry.py`:

(2a) Add the import near the top of the file, alongside the other prompt imports:

```python
from backend.modules.integrations._screen_effects_prompt import SCREEN_EFFECT_PROMPT
```

(2b) Inside `_register_builtins()`, after the last existing `register(...)` call (xai_voice), append:

```python
    register(IntegrationDefinition(
        id="screen_effect",
        display_name="Screen Effects",
        description="Visual inline flourishes the persona drops over the screen.",
        icon="sparkles",
        execution_mode="frontend",
        config_fields=[],
        capabilities=[],
        system_prompt_template=SCREEN_EFFECT_PROMPT,
        response_tag_prefix="screen_effect",
        tool_definitions=[],
        default_enabled=True,
        assignable=False,
    ))
```

- [ ] **Step 3: Write the failing definition test**

Write `backend/tests/modules/integrations/test_screen_effect_definition.py`:

```python
"""Smoke checks on the ``screen_effect`` integration definition.

Pure import-only; no DB, no FastAPI app. Catches accidental drift between
the spec (default_enabled, assignable, response_tag_prefix == id) and the
registration call.
"""

from backend.modules.integrations._registry import get


def test_screen_effect_is_registered() -> None:
    definition = get("screen_effect")
    assert definition is not None, "screen_effect integration must be registered"


def test_screen_effect_is_default_on_for_every_user() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert definition.default_enabled is True
    assert definition.assignable is False


def test_screen_effect_response_tag_prefix_matches_id() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert definition.response_tag_prefix == definition.id == "screen_effect"


def test_screen_effect_has_prompt_extension() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert "rising_emojis" in definition.system_prompt_template
    assert "<screen_effect" in definition.system_prompt_template


def test_screen_effect_has_no_tools() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert definition.tool_definitions == []
    assert definition.capabilities == []
```

If `backend/tests/modules/integrations/__init__.py` does not yet exist, create it as an empty file in the same step.

- [ ] **Step 4: Run the test — it should pass**

Run from the project root:

```bash
uv run pytest backend/tests/modules/integrations/test_screen_effect_definition.py -v
```

Expected: 5 tests pass. The test verifies the registration call wrote in Step 2; if any assertion fails, fix the registration in `_registry.py` before continuing.

- [ ] **Step 5: Quick syntax check**

```bash
uv run python -m py_compile \
  backend/modules/integrations/_screen_effects_prompt.py \
  backend/modules/integrations/_registry.py \
  backend/tests/modules/integrations/test_screen_effect_definition.py
```

Expected: silent (exit code 0).

- [ ] **Step 6: Commit**

```bash
git add \
  backend/modules/integrations/_screen_effects_prompt.py \
  backend/modules/integrations/_registry.py \
  backend/tests/modules/integrations/__init__.py \
  backend/tests/modules/integrations/test_screen_effect_definition.py
git commit -m "Add screen_effect integration definition and prompt"
```

---

### Task 2: Frontend — `risingEmojis` effect (parser + pill builder, TDD)

**Files:**
- Create: `frontend/src/features/integrations/plugins/screen_effects/effects/risingEmojis.ts`
- Create: `frontend/src/features/integrations/plugins/screen_effects/__tests__/risingEmojis.test.ts`

**Background:** The plugin parses a tag like `<screen_effect rising_emojis 💖 🤘 🔥>` synchronously into a `TagExecutionResult`. Args may be space-separated (each arg is one grapheme) OR concatenated (one arg holds all emojis). Compound emojis (ZWJ sequences, skin-tone modifiers) must stay intact, hence `Intl.Segmenter` with `granularity: 'grapheme'`. Hard cap at 5 distinct emojis. `TagExecutionResult` and `IntegrationPlugin` are already declared in `frontend/src/features/integrations/types.ts`.

- [ ] **Step 1: Write the failing test**

Write `frontend/src/features/integrations/plugins/screen_effects/__tests__/risingEmojis.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { risingEmojis, parseEmojis } from '../effects/risingEmojis'

describe('parseEmojis', () => {
  it('returns space-separated emojis as-is', () => {
    expect(parseEmojis(['💖', '🤘', '🔥'])).toEqual(['💖', '🤘', '🔥'])
  })

  it('splits a concatenated emoji string into graphemes', () => {
    expect(parseEmojis(['💖🤘🔥'])).toEqual(['💖', '🤘', '🔥'])
  })

  it('dedupes across all args', () => {
    expect(parseEmojis(['💖', '💖🤘'])).toEqual(['💖', '🤘'])
  })

  it('keeps ZWJ sequences intact', () => {
    expect(parseEmojis(['👨‍👩‍👧'])).toEqual(['👨‍👩‍👧'])
  })

  it('keeps skin-tone modifiers intact', () => {
    expect(parseEmojis(['👋🏽'])).toEqual(['👋🏽'])
  })

  it('returns an empty array for no args', () => {
    expect(parseEmojis([])).toEqual([])
  })

  it('caps the result at 5 distinct emojis', () => {
    expect(parseEmojis(['💖🤘🔥💪🎉🌈'])).toHaveLength(5)
  })

  it('ignores whitespace graphemes', () => {
    expect(parseEmojis(['  💖  '])).toEqual(['💖'])
  })
})

describe('risingEmojis', () => {
  it('returns a pill with icon + command + emojis for valid args', () => {
    const result = risingEmojis(['💖', '🤘', '🔥'])
    expect(result.pillContent).toBe('✨ rising_emojis 💖🤘🔥')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      effect: 'rising_emojis',
      emojis: ['💖', '🤘', '🔥'],
    })
    expect(result.sideEffect).toBeUndefined()
  })

  it('falls back to a sparkle when no emojis are given', () => {
    const result = risingEmojis([])
    expect(result.pillContent).toBe('✨ rising_emojis (no emojis)')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      effect: 'rising_emojis',
      emojis: ['✨'],
    })
  })

  it('caps payload emojis at MAX_EMOJIS', () => {
    const result = risingEmojis(['💖🤘🔥💪🎉🌈'])
    const payload = result.effectPayload as { emojis: string[] }
    expect(payload.emojis).toHaveLength(5)
  })
})
```

- [ ] **Step 2: Run the test — verify it fails**

Run from `frontend/`:

```bash
pnpm vitest run src/features/integrations/plugins/screen_effects/__tests__/risingEmojis.test.ts
```

Expected: FAIL with module-not-found error for `../effects/risingEmojis`.

- [ ] **Step 3: Implement the effect builder**

Write `frontend/src/features/integrations/plugins/screen_effects/effects/risingEmojis.ts`:

```typescript
import type { TagExecutionResult } from '../../../types'

const MAX_EMOJIS = 5
const FALLBACK_EMOJI = '✨'

/**
 * Build a TagExecutionResult for the rising_emojis effect.
 *
 * Pure / deterministic over (args). No randomness — the visible randomness
 * (per-particle size, drift, rotation) lives in RisingEmojisEffect at spawn
 * time so live-stream and persisted re-renders produce identical pills.
 */
export function risingEmojis(args: string[]): TagExecutionResult {
  const emojis = parseEmojis(args)
  if (emojis.length === 0) {
    return {
      pillContent: '✨ rising_emojis (no emojis)',
      syncWithTts: true,
      effectPayload: { effect: 'rising_emojis', emojis: [FALLBACK_EMOJI] },
    }
  }
  return {
    pillContent: `✨ rising_emojis ${emojis.join('')}`,
    syncWithTts: true,
    effectPayload: { effect: 'rising_emojis', emojis },
  }
}

/**
 * Split args into a deduped list of grapheme-correct emoji clusters.
 *
 * Accepts both space-separated args (`['💖', '🤘', '🔥']`) and a single
 * concatenated string (`['💖🤘🔥']`); ZWJ sequences and skin-tone modifiers
 * are preserved as a single grapheme. Whitespace-only segments are dropped.
 * Hard-capped at MAX_EMOJIS to bound the visual cost.
 */
export function parseEmojis(args: string[]): string[] {
  const seg = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  const out: string[] = []
  const seen = new Set<string>()
  for (const arg of args) {
    for (const { segment } of seg.segment(arg)) {
      const trimmed = segment.trim()
      if (!trimmed) continue
      if (seen.has(trimmed)) continue
      seen.add(trimmed)
      out.push(trimmed)
      if (out.length >= MAX_EMOJIS) return out
    }
  }
  return out
}
```

- [ ] **Step 4: Run the test — verify it passes**

```bash
pnpm vitest run src/features/integrations/plugins/screen_effects/__tests__/risingEmojis.test.ts
```

Expected: 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add \
  frontend/src/features/integrations/plugins/screen_effects/effects/risingEmojis.ts \
  frontend/src/features/integrations/plugins/screen_effects/__tests__/risingEmojis.test.ts
git commit -m "Add rising_emojis effect parser and pill builder"
```

---

### Task 3: Frontend — `executeTag` dispatcher (TDD)

**Files:**
- Create: `frontend/src/features/integrations/plugins/screen_effects/tags.ts`
- Create: `frontend/src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts`

**Background:** `executeTag(command, args, config)` is the synchronous entry point invoked by the buffer when a `<screen_effect …>` tag is detected. It dispatches `command` to the matching effect builder via a tiny `Record<string, EffectFn>` map. Unknown commands return a non-throwing "unknown" pill. The dispatcher does not crash on unexpected casing.

- [ ] **Step 1: Write the failing test**

Write `frontend/src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { executeTag } from '../tags'

describe('screen_effect executeTag', () => {
  it('dispatches rising_emojis to the effect builder', () => {
    const result = executeTag('rising_emojis', ['💖', '🤘'], {})
    expect(result.pillContent).toBe('✨ rising_emojis 💖🤘')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      effect: 'rising_emojis',
      emojis: ['💖', '🤘'],
    })
  })

  it('lower-cases the command before dispatching', () => {
    const result = executeTag('Rising_Emojis', ['💖'], {})
    expect(result.pillContent).toBe('✨ rising_emojis 💖')
  })

  it('returns an "unknown" pill for an unrecognised command', () => {
    const result = executeTag('cartwheel', [], {})
    expect(result.pillContent).toBe('screen_effect: unknown "cartwheel"')
    expect(result.syncWithTts).toBe(true)
    expect(result.effectPayload).toEqual({
      error: 'unknown_effect',
      command: 'cartwheel',
    })
    expect(result.sideEffect).toBeUndefined()
  })

  it('does not throw on empty args for a known command', () => {
    const result = executeTag('rising_emojis', [], {})
    expect(result.pillContent).toBe('✨ rising_emojis (no emojis)')
  })
})
```

- [ ] **Step 2: Run the test — verify it fails**

```bash
pnpm vitest run src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts
```

Expected: FAIL with module-not-found error for `../tags`.

- [ ] **Step 3: Implement the dispatcher**

Write `frontend/src/features/integrations/plugins/screen_effects/tags.ts`:

```typescript
import type { TagExecutionResult } from '../../types'
import { risingEmojis } from './effects/risingEmojis'

type EffectFn = (args: string[]) => TagExecutionResult

const EFFECTS: Record<string, EffectFn> = {
  rising_emojis: risingEmojis,
}

/**
 * Dispatch a screen_effect tag to its effect builder.
 *
 * Synchronous, deterministic over (command, args). Unknown commands return
 * an "unknown" pill — the buffer's error pill is reserved for thrown
 * exceptions, which we deliberately avoid.
 */
export function executeTag(
  command: string,
  args: string[],
  _config: Record<string, unknown>,
): TagExecutionResult {
  const fn = EFFECTS[command.toLowerCase()]
  if (!fn) {
    return {
      pillContent: `screen_effect: unknown "${command}"`,
      syncWithTts: true,
      effectPayload: { error: 'unknown_effect', command },
    }
  }
  return fn(args)
}
```

- [ ] **Step 4: Run the test — verify it passes**

```bash
pnpm vitest run src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add \
  frontend/src/features/integrations/plugins/screen_effects/tags.ts \
  frontend/src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts
git commit -m "Add executeTag dispatcher for screen_effect plugin"
```

---

### Task 4: Frontend — Plugin registration shim

**Files:**
- Create: `frontend/src/features/integrations/plugins/screen_effects/index.ts`

**Background:** The plugin registers itself with the frontend integration registry as a side-effect on import (matching the Lovense / Mistral / xAI pattern). No tests — registration is verified via the build and via the existing `pluginLifecycle.test.ts` which ensures plugins of registered integrations have an `executeTag`.

- [ ] **Step 1: Write the registration shim**

Write `frontend/src/features/integrations/plugins/screen_effects/index.ts`:

```typescript
import type { IntegrationPlugin } from '../../types'
import { registerPlugin } from '../../registry'
import { executeTag } from './tags'

const screenEffectsPlugin: IntegrationPlugin = {
  id: 'screen_effect',
  executeTag,
}

registerPlugin(screenEffectsPlugin)

export default screenEffectsPlugin
```

- [ ] **Step 2: Type-check**

From `frontend/`:

```bash
pnpm tsc --noEmit -p tsconfig.app.json
```

Expected: clean (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/integrations/plugins/screen_effects/index.ts
git commit -m "Register screen_effect plugin with frontend registry"
```

---

### Task 5: Frontend — `RisingEmojisEffect` component

**Files:**
- Create: `frontend/src/features/integrations/plugins/screen_effects/overlay/RisingEmojisEffect.tsx`
- Create: `frontend/src/features/integrations/plugins/screen_effects/__tests__/RisingEmojisEffect.smoke.test.tsx`

**Background:** A self-contained component that, on mount, spawns `count` DOM `<span>` particles distributed over `spawnMs` and translates them upward via CSS keyframe animation, calls `onDone` when all particles have completed. Each particle has randomised size, horizontal drift, rotation, animation duration, and spawn delay — random parameters live here, not in the plugin, so the live-vs-persisted pill equivalence invariant holds. The "Subtil" preset (count=14) was validated in the design phase.

The smoke test verifies mount + spawn-on-effect + cleanup-via-onDone using fake timers; it does not assert exact DOM positions or pixel values.

- [ ] **Step 1: Implement the component**

Write `frontend/src/features/integrations/plugins/screen_effects/overlay/RisingEmojisEffect.tsx`:

```typescript
import { useEffect, useRef } from 'react'

interface Profile {
  count: number
  spawnMs: number
  sizeMin: number
  sizeMax: number
  drift: number
  riseMsMin: number
  riseMsMax: number
}

const PROFILE_FULL: Profile = {
  count: 14,
  spawnMs: 1400,
  sizeMin: 22,
  sizeMax: 38,
  drift: 30,
  riseMsMin: 1900,
  riseMsMax: 2500,
}

const PROFILE_REDUCED: Profile = {
  count: 4,
  spawnMs: 1200,
  sizeMin: 22,
  sizeMax: 30,
  drift: 12,
  riseMsMin: 2300,
  riseMsMax: 2900,
}

const KEYFRAME_NAME = 'screenEffectsRise'

interface Props {
  emojis: string[]
  reduced: boolean
  onDone: () => void
}

/**
 * Renders one burst of rising emojis. Self-contained: appends spans to its
 * own container on mount, removes them on animationend, calls onDone after
 * the last particle finishes. Random parameters per particle are picked
 * here so persisted re-renders (which never invoke this component) cannot
 * differ visually from live ones.
 */
export function RisingEmojisEffect({ emojis, reduced, onDone }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const calledDoneRef = useRef(false)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const profile = reduced ? PROFILE_REDUCED : PROFILE_FULL
    const safeEmojis = emojis.length > 0 ? emojis : ['✨']
    const stageWidth = window.innerWidth
    const stageHeight = window.innerHeight
    let remaining = profile.count
    const timeouts: number[] = []

    const finish = () => {
      remaining -= 1
      if (remaining <= 0 && !calledDoneRef.current) {
        calledDoneRef.current = true
        onDone()
      }
    }

    for (let i = 0; i < profile.count; i += 1) {
      const delay = (i / profile.count) * profile.spawnMs + Math.random() * 120
      const emoji = safeEmojis[Math.floor(Math.random() * safeEmojis.length)]
      const startX = Math.random() * (stageWidth - 40) + 20
      const driftX = (Math.random() - 0.5) * profile.drift * 2
      const size = profile.sizeMin + Math.random() * (profile.sizeMax - profile.sizeMin)
      const rotateStart = (Math.random() - 0.5) * 30
      const rotateEnd = rotateStart + (Math.random() - 0.5) * 90
      const rise = stageHeight + size + 30
      const duration =
        profile.riseMsMin + Math.random() * (profile.riseMsMax - profile.riseMsMin)

      const span = document.createElement('span')
      span.className = 'screen-effect-rising-emoji'
      span.textContent = emoji
      span.style.position = 'absolute'
      span.style.left = `${startX}px`
      span.style.bottom = `${-(size + 20)}px`
      span.style.fontSize = `${size}px`
      span.style.lineHeight = '1'
      span.style.pointerEvents = 'none'
      span.style.userSelect = 'none'
      span.style.willChange = 'transform, opacity'
      span.style.setProperty('--screen-effect-dx', `${driftX}px`)
      span.style.setProperty('--screen-effect-rise', `${rise}px`)
      span.style.setProperty('--screen-effect-rs', `${rotateStart}deg`)
      span.style.setProperty('--screen-effect-re', `${rotateEnd}deg`)
      span.style.animation = `${KEYFRAME_NAME} ${duration}ms cubic-bezier(0.25, 0.6, 0.4, 1) ${delay}ms forwards`

      const onEnd = () => {
        span.removeEventListener('animationend', onEnd)
        if (span.parentNode) span.parentNode.removeChild(span)
        finish()
      }
      span.addEventListener('animationend', onEnd)
      // Safety: even if animationend never fires (jsdom, tab backgrounded),
      // schedule a fallback removal so onDone is still called.
      const safetyTimeout = window.setTimeout(() => {
        if (span.parentNode) {
          span.dispatchEvent(new Event('animationend'))
        }
      }, delay + duration + 500)
      timeouts.push(safetyTimeout)
      container.appendChild(span)
    }

    return () => {
      timeouts.forEach((t) => window.clearTimeout(t))
      while (container.firstChild) {
        container.removeChild(container.firstChild)
      }
    }
  }, [emojis, reduced, onDone])

  return (
    <>
      <style>{`
        @keyframes ${KEYFRAME_NAME} {
          0% {
            transform: translate(0, 0) rotate(var(--screen-effect-rs, 0deg)) scale(0.6);
            opacity: 0;
          }
          10% {
            transform: translate(
              calc(var(--screen-effect-dx) * 0.1),
              calc(var(--screen-effect-rise) * -0.1)
            ) rotate(calc(var(--screen-effect-rs) + (var(--screen-effect-re) - var(--screen-effect-rs)) * 0.1)) scale(1);
            opacity: 1;
          }
          85% {
            opacity: 1;
          }
          100% {
            transform: translate(
              var(--screen-effect-dx),
              calc(var(--screen-effect-rise) * -1)
            ) rotate(var(--screen-effect-re, 0deg)) scale(0.9);
            opacity: 0;
          }
        }
      `}</style>
      <div
        ref={containerRef}
        style={{
          position: 'absolute',
          inset: 0,
          overflow: 'hidden',
          pointerEvents: 'none',
        }}
      />
    </>
  )
}
```

- [ ] **Step 2: Write the smoke test**

Write `frontend/src/features/integrations/plugins/screen_effects/__tests__/RisingEmojisEffect.smoke.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { RisingEmojisEffect } from '../overlay/RisingEmojisEffect'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
})

describe('RisingEmojisEffect smoke', () => {
  it('mounts and spawns particles for the full profile', () => {
    const onDone = vi.fn()
    const { container } = render(
      <RisingEmojisEffect emojis={['💖', '🤘', '🔥']} reduced={false} onDone={onDone} />,
    )
    // Spawning happens inside useEffect on mount; jsdom executes it immediately.
    const spans = container.querySelectorAll('span.screen-effect-rising-emoji')
    expect(spans.length).toBe(14) // PROFILE_FULL.count
  })

  it('uses the reduced profile when reduced=true', () => {
    const onDone = vi.fn()
    const { container } = render(
      <RisingEmojisEffect emojis={['💖']} reduced onDone={onDone} />,
    )
    const spans = container.querySelectorAll('span.screen-effect-rising-emoji')
    expect(spans.length).toBe(4) // PROFILE_REDUCED.count
  })

  it('falls back to a sparkle when emojis is empty', () => {
    const onDone = vi.fn()
    const { container } = render(
      <RisingEmojisEffect emojis={[]} reduced onDone={onDone} />,
    )
    const spans = container.querySelectorAll('span.screen-effect-rising-emoji')
    expect(spans.length).toBeGreaterThan(0)
    Array.from(spans).forEach((s) => {
      expect(s.textContent).toBe('✨')
    })
  })

  it('calls onDone after the safety timeout elapses', () => {
    const onDone = vi.fn()
    render(<RisingEmojisEffect emojis={['💖']} reduced onDone={onDone} />)
    expect(onDone).not.toHaveBeenCalled()
    // Safety timeout = delay + duration + 500. Reduced profile worst case
    // is spawnMs (1200) + riseMsMax (2900) + 500 = 4600ms. Advance 6s.
    vi.advanceTimersByTime(6000)
    expect(onDone).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 3: Run the smoke test**

```bash
pnpm vitest run src/features/integrations/plugins/screen_effects/__tests__/RisingEmojisEffect.smoke.test.tsx
```

Expected: 4 tests pass. If "react/jsx-runtime" or test renderer issues come up, check that `@testing-library/react` is already a dev dependency (it is — `pluginLifecycle.test.ts` and other existing tests use it).

- [ ] **Step 4: Commit**

```bash
git add \
  frontend/src/features/integrations/plugins/screen_effects/overlay/RisingEmojisEffect.tsx \
  frontend/src/features/integrations/plugins/screen_effects/__tests__/RisingEmojisEffect.smoke.test.tsx
git commit -m "Add RisingEmojisEffect particle component"
```

---

### Task 6: Frontend — `ScreenEffectsOverlay` component

**Files:**
- Create: `frontend/src/features/integrations/plugins/screen_effects/overlay/ScreenEffectsOverlay.tsx`

**Background:** The overlay is mounted once at the App root. It subscribes to `Topics.INTEGRATION_INLINE_TRIGGER` on mount, filters bus events for `integration_id === 'screen_effect'`, dispatches by `payload.effect` to the matching effect component, and renders any active effects in parallel. `prefers-reduced-motion` is read once at mount and passed to each effect. No automated test — the overlay is a thin wiring layer; behaviour is covered by the manual checklist in Task 9.

The bus event payload type comes from `frontend/src/features/integrations/types.ts` (`IntegrationInlineTrigger`). The bus envelope's payload is the trigger object itself (see `inlineTriggerBus.ts:26-29`).

- [ ] **Step 1: Implement the overlay**

Write `frontend/src/features/integrations/plugins/screen_effects/overlay/ScreenEffectsOverlay.tsx`:

```typescript
import { useEffect, useState } from 'react'
import { eventBus } from '../../../../../core/websocket/eventBus'
import { Topics } from '../../../../../core/types/events'
import type { IntegrationInlineTrigger } from '../../../types'
import { RisingEmojisEffect } from './RisingEmojisEffect'

type ActiveEffect = {
  id: string
  kind: 'rising_emojis'
  emojis: string[]
  reduced: boolean
}

/**
 * Globally-mounted overlay that subscribes to INTEGRATION_INLINE_TRIGGER
 * events for the screen_effect integration and renders one short-lived
 * effect component per trigger. Effects overlap freely; each removes
 * itself from the active list via its own onDone callback.
 */
export function ScreenEffectsOverlay() {
  const [active, setActive] = useState<ActiveEffect[]>([])

  useEffect(() => {
    const reduced = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches
    return eventBus.on(Topics.INTEGRATION_INLINE_TRIGGER, (event) => {
      const trigger = event.payload as IntegrationInlineTrigger
      if (trigger.integration_id !== 'screen_effect') return
      const payload = trigger.payload as
        | { effect?: string; emojis?: string[] }
        | undefined
      if (!payload || payload.effect !== 'rising_emojis') return
      const id = crypto.randomUUID()
      setActive((prev) => [
        ...prev,
        {
          id,
          kind: 'rising_emojis',
          emojis: payload.emojis ?? ['✨'],
          reduced,
        },
      ])
    })
  }, [])

  const remove = (id: string) =>
    setActive((prev) => prev.filter((e) => e.id !== id))

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 90,
        overflow: 'hidden',
      }}
      aria-hidden="true"
      data-testid="screen-effects-overlay"
    >
      {active.map((e) =>
        e.kind === 'rising_emojis' ? (
          <RisingEmojisEffect
            key={e.id}
            emojis={e.emojis}
            reduced={e.reduced}
            onDone={() => remove(e.id)}
          />
        ) : null,
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
pnpm tsc --noEmit -p tsconfig.app.json
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/integrations/plugins/screen_effects/overlay/ScreenEffectsOverlay.tsx
git commit -m "Add ScreenEffectsOverlay subscriber and dispatcher"
```

---

### Task 7: Frontend — Wire plugin into App

**Files:**
- Modify: `frontend/src/App.tsx` — add the side-effect plugin import and mount the overlay.

**Background:** Existing plugin imports sit at lines 11-13 (Lovense, Mistral, xAI). The overlay must be a sibling to `<Routes>` inside `AppRoutes` so it is mounted exactly once and survives route changes.

- [ ] **Step 1: Add the side-effect import**

In `frontend/src/App.tsx`, after the existing `import './features/integrations/plugins/xai_voice'` line, add:

```typescript
import './features/integrations/plugins/screen_effects'
```

So the block becomes:

```typescript
import './features/integrations/plugins/lovense'
import './features/integrations/plugins/mistral_voice'
import './features/integrations/plugins/xai_voice'
import './features/integrations/plugins/screen_effects'
```

- [ ] **Step 2: Import the overlay component**

Below the other top-level imports, add:

```typescript
import { ScreenEffectsOverlay } from './features/integrations/plugins/screen_effects/overlay/ScreenEffectsOverlay'
```

- [ ] **Step 3: Mount the overlay inside `AppRoutes`**

Locate the JSX `return` block of `AppRoutes` (currently `return ( <> <LastRouteTracker /> <Routes> ... </Routes> </> )`). Add the overlay as a sibling AFTER `</Routes>` and BEFORE the closing `</>`:

Before:

```tsx
return (
  <>
    <LastRouteTracker />
    <Routes>
      ...
    </Routes>
  </>
)
```

After:

```tsx
return (
  <>
    <LastRouteTracker />
    <Routes>
      ...
    </Routes>
    <ScreenEffectsOverlay />
  </>
)
```

- [ ] **Step 4: Type-check**

```bash
pnpm tsc --noEmit -p tsconfig.app.json
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "Mount ScreenEffectsOverlay and register screen_effect plugin"
```

---

### Task 8: Frontend — Extend live-vs-persisted equivalence test

**Files:**
- Modify: `frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts`

**Background:** The existing regression test parametrises over a mock plugin to verify both buffer paths produce identical pill DOM. We add a new `describe` block (or reuse the existing one) that runs the same assertions for the screen_effect tag. The mock plugin uses the real `executeTag` from the screen_effects plugin so we test the full path including parsing.

- [ ] **Step 1: Read the existing test**

Open `frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts` and re-read the helper `withMocks` (around lines 60-78) plus the existing `it(...)` blocks. The helper takes a plugin object and a test function; the function gets a freshly-imported `responseTagProcessor` module.

- [ ] **Step 2: Update the `withMocks` integration definition fixture**

The existing `withMocks` helper hard-codes a `lovense` definition in the mocked `useIntegrationsStore`. We need a `screen_effect` definition there too so the buffer's `getTagPrefixes()` includes it. **Edit the existing helper**, not a new one — both tests benefit from the broader fixture and the change is harmless.

In the `vi.doMock('../../integrations/store', ...)` block (around lines 65-77), replace the `definitions` array so it lists both:

```typescript
        definitions: [
          { id: 'lovense', has_response_tags: true },
          { id: 'screen_effect', has_response_tags: true },
        ],
```

- [ ] **Step 3: Add the new test case**

After the existing two `it(...)` blocks inside `describe('live vs persisted pill equivalence', () => { ... })`, append the case below. It mirrors the Lovense test exactly — same constructor signature, same `process(...)` call, same DOM-comparison flow — only the plugin and the asserted pill string differ.

```typescript
  it('produces identical pill DOM for a screen_effect tag in both paths', async () => {
    const { executeTag: realExecuteTag } = await import(
      '../../integrations/plugins/screen_effects/tags'
    )
    const executeTag = (
      cmd: string,
      args: string[],
      cfg: Record<string, unknown>,
    ): TagExecutionResult => realExecuteTag(cmd, args, cfg)

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const rawTag = '<screen_effect rising_emojis 💖 🤘 🔥>'

      // LIVE path: side effects ON, source = live_stream.
      const livePending = new Map<string, PendingEffect>()
      const livePills = new Map<string, string>()
      const liveBuffer = new ResponseTagBuffer(
        () => undefined,
        'live_stream',
        livePending,
        () => undefined,
        livePills,
        { runSideEffects: true },
      )
      const liveOut = liveBuffer.process(rawTag)

      // PERSISTED path: side effects OFF, source = text_only.
      const persistedPending = new Map<string, PendingEffect>()
      const persistedPills = new Map<string, string>()
      const persistedBuffer = new ResponseTagBuffer(
        () => undefined,
        'text_only',
        persistedPending,
        () => undefined,
        persistedPills,
        { runSideEffects: false },
      )
      const persistedOut = persistedBuffer.process(rawTag)

      // 1. Same pill content string in both maps.
      expect(livePills.size).toBe(1)
      expect(persistedPills.size).toBe(1)
      const livePillContent = [...livePills.values()][0]
      const persistedPillContent = [...persistedPills.values()][0]
      expect(livePillContent).toBe(persistedPillContent)
      expect(livePillContent).toBe('✨ rising_emojis 💖🤘🔥')

      // 2. Both outputs are placeholders (UUIDs differ by design).
      expect(liveOut).toMatch(PLACEHOLDER_RE)
      expect(persistedOut).toMatch(PLACEHOLDER_RE)

      // 3. Rehype DOM is identical when fed either path's map after
      //    placeholder UUIDs are normalised to a fixed sentinel.
      const liveId = [...livePills.keys()][0]
      const persistedId = [...persistedPills.keys()][0]
      const SENTINEL = '00000000-0000-4000-8000-000000000000'
      const liveNormalised = liveOut.replace(liveId, SENTINEL)
      const persistedNormalised = persistedOut.replace(persistedId, SENTINEL)
      expect(liveNormalised).toBe(persistedNormalised)

      const liveDom = renderPills(
        liveNormalised,
        new Map([[SENTINEL, livePillContent]]),
      )
      const persistedDom = renderPills(
        persistedNormalised,
        new Map([[SENTINEL, persistedPillContent]]),
      )
      expect(liveDom).toBe(persistedDom)
      expect(liveDom).toContain(
        '<span class="integration-pill">✨ rising_emojis 💖🤘🔥</span>',
      )

      // 4. screen_effect plugin has no sideEffect, so there is nothing to
      //    assert about side-effect invocation. The lovense test covers the
      //    runSideEffects flag separately.
    })
  })
```

- [ ] **Step 4: Run the test**

```bash
pnpm vitest run src/features/chat/__tests__/livePersistedPillEquivalence.test.ts
```

Expected: all tests pass (existing 2 + new 1 = 3).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts
git commit -m "Cover screen_effect tag in live-vs-persisted equivalence test"
```

---

### Task 9: Final build verification

**Files:** none (verification only)

**Background:** A clean `pnpm run build` is the canonical signal that nothing is broken. `tsc --noEmit` alone is not sufficient: `pnpm run build` runs `tsc -b` which catches stricter project-reference issues that the looser one-file check misses. This is the gate before the manual verification phase.

- [ ] **Step 1: Run the full frontend build**

From `frontend/`:

```bash
pnpm run build
```

Expected: clean exit. Investigate and fix any error before continuing.

- [ ] **Step 2: Run the full screen_effects test suite**

From `frontend/`:

```bash
pnpm vitest run src/features/integrations/plugins/screen_effects/
```

Expected: all tests in the three test files pass (parser + dispatcher + smoke = 19 tests total).

- [ ] **Step 3: Run the equivalence test**

```bash
pnpm vitest run src/features/chat/__tests__/livePersistedPillEquivalence.test.ts
```

Expected: 3 tests pass.

- [ ] **Step 4: Run the backend definition test**

From the project root:

```bash
uv run pytest backend/tests/modules/integrations/test_screen_effect_definition.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: No commit (verification only)**

If everything was already committed in earlier tasks, this task does not produce a new commit. If anything had to be fixed, that fix is committed under the relevant earlier task's wording — not under "Final build verification".

---

### Task 10: Manual verification checklist

**Files:** none (operator action)

**Background:** Animation feel is not snapshot-testable. The list below comes from the spec's "Manual verification" section. The agent should NOT execute these — they are for Chris on a real device.

- [ ] **Step 1: Tick the manual checklist on a real device**

Run a dev backend + frontend, log in as a fresh user, then verify each of the following. The spec lists them as items 1-10 of section 10:

1. **Default-on after migration.** Fresh user has the integration active without an explicit config doc.
2. **Live stream + TTS.** With xAI Voice (or Mistral Voice) active, prompt the LLM to celebrate. Storm starts on the spoken word, not before.
3. **Live stream + text-only.** TTS off, same prompt. Storm starts immediately.
4. **History re-render.** Page reload after a successful storm. Pill remains; **no** storm replays.
5. **Read-aloud.** Trigger "read aloud" on the persisted message. Storm plays at full intensity again.
6. **User toggle off.** Disable Screen Effects in the Integrations tab. New chat turn → no `<screen_effect>` tag emitted, no storm.
7. **`prefers-reduced-motion`.** OS-level "Reduce motion" on. Trigger the effect. Storm is markedly calmer.
8. **Compound emojis.** Provoke a tag with `👨‍👩‍👧 🌈`. Both render correctly, no broken glyphs.
9. **Mobile** (under `lg` breakpoint). Storm renders correctly above the mobile drawer.
10. **Parallel tags.** LLM emits two `<screen_effect rising_emojis ...>` tags in one answer. Both storms play; both pills appear.

- [ ] **Step 2: Report**

Once Chris has ticked the list, the implementation phase is complete. The merge-to-master step is performed by the parent agent driving the plan, not by any subagent.

---

## Self-Review

**Spec coverage:**
- Section 1 (Motivation) — informational, no code work.
- Section 2 (Goals & non-goals) — covered by Tasks 1, 2, 3, 5, 6, 7 (default-on, opt-out, rising_emojis, TTS sync, read-aloud, reduced-motion, equivalence, parallel tags via the active-array).
- Section 3 (Architecture overview) — Tasks 1, 4, 5, 6, 7.
- Section 4 (Backend `IntegrationDefinition`) — Task 1.
- Section 5 (Frontend plugin) — Tasks 2, 3, 4.
- Section 6 (Render layer) — Tasks 5, 6, 7.
- Section 7 (Behaviour matrix) — implicit in Tasks 5/6 (reduced motion, fallback emoji, unknown command pill, multi-tag overlap) and explicit in Task 10 (manual).
- Section 8 (Equivalence invariant) — Tasks 2, 8.
- Section 9 (Testing) — Tasks 1, 2, 3, 5, 8, 9.
- Section 10 (Manual verification) — Task 10.
- Section 11 (Future effects) — informational.
- Section 12 (Migration considerations) — covered by `default_enabled=True` in Task 1.
- Section 13 (Out-of-scope reminders) — informational.

No spec requirement is unmapped.

**Type / name consistency:**
- `risingEmojis(args)`, `parseEmojis(args)`, `executeTag(command, args, _config)` — same names everywhere.
- `MAX_EMOJIS = 5` — defined in `effects/risingEmojis.ts`, referenced consistently in tests.
- `pillContent` format `'✨ rising_emojis 💖🤘🔥'` — same in builder, dispatcher tests, equivalence test.
- `effectPayload.effect === 'rising_emojis'` — same in builder, overlay subscriber.
- `Topics.INTEGRATION_INLINE_TRIGGER` — verified in `frontend/src/core/types/events.ts`.
- `IntegrationInlineTrigger` shape — verified against `frontend/src/features/integrations/types.ts:138-150`.

**Placeholder scan:** none of "TBD", "TODO", "implement later", "fill in details", "similar to Task N" appear in the plan.
