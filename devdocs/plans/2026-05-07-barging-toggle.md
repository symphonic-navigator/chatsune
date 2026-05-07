# Barging Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Critical constraints for any dispatched subagent:**
> - Do **NOT** merge, push, or switch branches.
> - Stay on `feat/barging-toggle`.
> - Run `pnpm run build` (not just `pnpm tsc --noEmit`) before declaring a task complete — `tsc -b` catches stricter errors that CI will hit.
> - Run `pnpm test` (vitest) for the relevant test file(s) introduced or touched.

**Goal:** Add a per-device toggle in the live-voice cockpit that lets the user disable barging — when off, the user's mic is held back while the persona is speaking, and a clear visual cue (pulsing mic-with-slash on the toggle) communicates the state.

**Architecture:** New persisted zustand store (`bargeSettingsStore`, localStorage). Pure-function gate (`shouldSuppressBarge`) tested in isolation. New self-contained UI component (`BargingToggleButton`, not `CockpitButton`-based — `CockpitButton`'s accent palette has no red). Single integration point in `useConversationMode.handleSpeechStart` extends the existing `micMuted` short-circuit. Cockpit slot rules: replaces the mobile `ⓘ` while live-active; adds a separator + the toggle on desktop after the Live button.

**Tech Stack:** React 18 + TypeScript + Tailwind, zustand 4 with `persist` middleware, vitest, existing voice/cockpit infrastructure.

**Spec:** `devdocs/specs/2026-05-07-barging-toggle-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `frontend/src/features/voice/stores/bargeSettingsStore.ts` | **create** | The single boolean preference, persisted to `localStorage['voice.barging.enabled']`. Default `true`. No other concerns. |
| `frontend/src/features/voice/stores/__tests__/bargeSettingsStore.test.ts` | **create** | Default value, toggle behaviour, persistence round-trip via mocked localStorage. |
| `frontend/src/features/voice/bargeGate.ts` | **create** | Pure function `shouldSuppressBarge(input)` — single source of truth for "is barging suppressed right now?". No imports from React, store, or DOM. |
| `frontend/src/features/voice/__tests__/bargeGate.test.ts` | **create** | Truth-table tests for the pure function. |
| `frontend/src/features/chat/cockpit/buttons/BargingToggleButton.tsx` | **create** | Self-contained styled button with three visual states (open lips green / lips+slash red / mic+slash red pulsing). Reads bargeSettingsStore + usePhase, calls store.toggle on click. |
| `frontend/src/features/chat/cockpit/buttons/__tests__/BargingToggleButton.test.tsx` | **create** | Renders correct glyph + colour + pulsation for each (enabled, phase) combo; click toggles. |
| `frontend/src/features/voice/hooks/useConversationMode.ts` | **modify** | Extend the existing `micMuted` short-circuit in `handleSpeechStart` to also fire when the bargeGate says suppress. One log line on suppression. |
| `frontend/src/features/chat/cockpit/CockpitBar.tsx` | **modify** | Mobile: replace `ⓘ` with `<BargingToggleButton />` when `liveActive === true`. Desktop: render `<Sep />` + `<BargingToggleButton />` after `<LiveButton />` when `liveActive === true`. |

**Unchanged (verify):** `bargeController.ts`, `VoiceButton.tsx`, all `responseTaskGroup` tests, all backend code. The blue mic-button's slash glyph keeps its sole meaning (`live-mic-muted` = user-muted).

---

## Task 1: bargeSettingsStore

**Files:**
- Create: `frontend/src/features/voice/stores/bargeSettingsStore.ts`
- Create: `frontend/src/features/voice/stores/__tests__/bargeSettingsStore.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/voice/stores/__tests__/bargeSettingsStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useBargeSettingsStore } from '../bargeSettingsStore'

describe('bargeSettingsStore', () => {
  beforeEach(() => {
    // Reset store to defaults and clear persisted state between tests.
    useBargeSettingsStore.setState({ enabled: true })
    window.localStorage.clear()
  })

  it('defaults to enabled=true', () => {
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('setEnabled writes the given value', () => {
    useBargeSettingsStore.getState().setEnabled(false)
    expect(useBargeSettingsStore.getState().enabled).toBe(false)
    useBargeSettingsStore.getState().setEnabled(true)
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('toggle flips the value', () => {
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
    useBargeSettingsStore.getState().toggle()
    expect(useBargeSettingsStore.getState().enabled).toBe(false)
    useBargeSettingsStore.getState().toggle()
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('persists the value to localStorage under voice.barging.enabled', () => {
    useBargeSettingsStore.getState().setEnabled(false)
    const raw = window.localStorage.getItem('voice.barging.enabled')
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!)
    expect(parsed.state.enabled).toBe(false)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter ./frontend test bargeSettingsStore`
Expected: FAIL with "Cannot find module '../bargeSettingsStore'".

- [ ] **Step 3: Create the store**

Create `frontend/src/features/voice/stores/bargeSettingsStore.ts`:

```ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface BargeSettingsState {
  enabled: boolean
  setEnabled: (next: boolean) => void
  toggle: () => void
}

/**
 * Per-device user preference for whether the user can interrupt the
 * persona's TTS playback by speaking ("barging on"), or whether the
 * mic is held back while the persona speaks ("barging off").
 *
 * Default true matches today's behaviour exactly. The state is purely
 * a user preference and is not reset on session/live-mode exit.
 *
 * See devdocs/specs/2026-05-07-barging-toggle-design.md.
 */
export const useBargeSettingsStore = create<BargeSettingsState>()(
  persist(
    (set) => ({
      enabled: true,
      setEnabled: (next) => set({ enabled: next }),
      toggle: () => set((s) => ({ enabled: !s.enabled })),
    }),
    { name: 'voice.barging.enabled' },
  ),
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter ./frontend test bargeSettingsStore`
Expected: all 4 tests PASS.

- [ ] **Step 5: Build check**

Run: `pnpm --filter ./frontend run build`
Expected: build succeeds, no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/stores/bargeSettingsStore.ts \
        frontend/src/features/voice/stores/__tests__/bargeSettingsStore.test.ts
git commit -m "$(cat <<'EOF'
Add bargeSettingsStore for per-device barging toggle

Single boolean preference persisted to localStorage under
'voice.barging.enabled'. Default true mirrors today's behaviour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: shouldSuppressBarge — pure gate function

**Files:**
- Create: `frontend/src/features/voice/bargeGate.ts`
- Create: `frontend/src/features/voice/__tests__/bargeGate.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/voice/__tests__/bargeGate.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { shouldSuppressBarge } from '../bargeGate'

describe('shouldSuppressBarge', () => {
  it('returns false when barging is enabled, regardless of group state', () => {
    expect(shouldSuppressBarge({ enabled: true, groupState: null })).toBe(false)
    expect(shouldSuppressBarge({ enabled: true, groupState: 'streaming' })).toBe(false)
    expect(shouldSuppressBarge({ enabled: true, groupState: 'tailing' })).toBe(false)
    expect(shouldSuppressBarge({ enabled: true, groupState: 'before-first-delta' })).toBe(false)
  })

  it('returns true when disabled and group is in speaking phase', () => {
    expect(shouldSuppressBarge({ enabled: false, groupState: 'streaming' })).toBe(true)
    expect(shouldSuppressBarge({ enabled: false, groupState: 'tailing' })).toBe(true)
  })

  it('returns false when disabled but group is not yet speaking', () => {
    // before-first-delta = phase 'thinking'. Mic suppression here would
    // be misleading — the user can still speak normally, the mic is just
    // closed by the natural pipeline (STT just sent its bundle).
    expect(shouldSuppressBarge({ enabled: false, groupState: 'before-first-delta' })).toBe(false)
  })

  it('returns false when disabled and there is no active group', () => {
    // Phase listening — barging-off must not suppress fresh speech.
    expect(shouldSuppressBarge({ enabled: false, groupState: null })).toBe(false)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter ./frontend test bargeGate`
Expected: FAIL with "Cannot find module '../bargeGate'".

- [ ] **Step 3: Create the gate function**

Create `frontend/src/features/voice/bargeGate.ts`:

```ts
import type { ResponseTaskGroup } from '../chat/responseTaskGroup'

export interface ShouldSuppressBargeInput {
  /** Live value of useBargeSettingsStore.enabled. */
  enabled: boolean
  /** Active Group's state, or null when no Group is active. */
  groupState: ResponseTaskGroup['state'] | null
}

/**
 * Pure decision function: given the user's barging preference and the
 * active Group's lifecycle state, should an incoming VAD onset be
 * suppressed (i.e. NOT promoted into a Barge)?
 *
 * Rule: suppress iff the user has turned barging off AND the persona
 * is currently emitting audio (Group is `streaming` or `tailing`,
 * matching the `speaking` phase from derivePhase).
 *
 * `before-first-delta` (phase `thinking`) is intentionally NOT
 * suppressed — there's no audio yet, the mic is naturally closed by
 * the STT pipeline anyway, and showing a suppression cue here would
 * be misleading.
 *
 * Listening / idle (groupState === null) is never suppressed:
 * barging-off only changes behaviour while the persona is speaking;
 * fresh user speech in a quiet moment must always go through.
 */
export function shouldSuppressBarge(input: ShouldSuppressBargeInput): boolean {
  if (input.enabled) return false
  return input.groupState === 'streaming' || input.groupState === 'tailing'
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter ./frontend test bargeGate`
Expected: all 4 tests PASS.

- [ ] **Step 5: Build check**

Run: `pnpm --filter ./frontend run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/bargeGate.ts \
        frontend/src/features/voice/__tests__/bargeGate.test.ts
git commit -m "$(cat <<'EOF'
Add shouldSuppressBarge pure gate for barging toggle

Single source of truth: given the user's preference and the active
Group state, should an incoming VAD onset be promoted into a Barge?
Suppression fires only when barging is off AND the Group is in
streaming/tailing (i.e. phase 'speaking'). Thinking and listening
phases pass through.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: BargingToggleButton component

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/BargingToggleButton.tsx`
- Create: `frontend/src/features/chat/cockpit/buttons/__tests__/BargingToggleButton.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/chat/cockpit/buttons/__tests__/BargingToggleButton.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BargingToggleButton } from '../BargingToggleButton'
import { useBargeSettingsStore } from '@/features/voice/stores/bargeSettingsStore'

// Mock usePhase so each test can pin the phase deterministically.
vi.mock('@/features/voice/usePhase', () => ({
  usePhase: vi.fn(),
}))
import { usePhase } from '@/features/voice/usePhase'

describe('BargingToggleButton', () => {
  beforeEach(() => {
    useBargeSettingsStore.setState({ enabled: true })
    window.localStorage.clear()
    vi.mocked(usePhase).mockReturnValue('listening')
  })

  it('renders the open-lips glyph in green when enabled (any phase)', () => {
    useBargeSettingsStore.setState({ enabled: true })
    vi.mocked(usePhase).mockReturnValue('speaking')
    render(<BargingToggleButton />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('data-barge-state', 'on')
    expect(btn.className).toMatch(/text-\[#4ade80\]|text-green/)
    expect(btn.querySelector('[data-glyph="lips-open"]')).not.toBeNull()
  })

  it('renders the lips-with-slash glyph in red, no pulse, when disabled and not speaking', () => {
    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('listening')
    render(<BargingToggleButton />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('data-barge-state', 'off-idle')
    expect(btn.className).toMatch(/text-\[#ef4444\]|text-red/)
    expect(btn.className).not.toMatch(/animate-pulse-slow/)
    expect(btn.querySelector('[data-glyph="lips-slash"]')).not.toBeNull()
  })

  it('renders the mic-with-slash glyph pulsing when disabled and speaking', () => {
    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('speaking')
    render(<BargingToggleButton />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('data-barge-state', 'off-speaking')
    expect(btn.className).toMatch(/text-\[#ef4444\]|text-red/)
    expect(btn.className).toMatch(/animate-pulse-slow/)
    expect(btn.querySelector('[data-glyph="mic-slash"]')).not.toBeNull()
  })

  it('toggles the store on click', () => {
    useBargeSettingsStore.setState({ enabled: true })
    render(<BargingToggleButton />)
    fireEvent.click(screen.getByRole('button'))
    expect(useBargeSettingsStore.getState().enabled).toBe(false)
    fireEvent.click(screen.getByRole('button'))
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('uses tooltip text matching the active state', () => {
    useBargeSettingsStore.setState({ enabled: true })
    const { rerender } = render(<BargingToggleButton />)
    expect(screen.getByRole('button').title).toMatch(/can interrupt/i)

    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('listening')
    rerender(<BargingToggleButton />)
    expect(screen.getByRole('button').title).toMatch(/can't be interrupted|tap to enable/i)

    vi.mocked(usePhase).mockReturnValue('speaking')
    rerender(<BargingToggleButton />)
    expect(screen.getByRole('button').title).toMatch(/asleep|while persona speaks/i)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter ./frontend test BargingToggleButton`
Expected: FAIL with "Cannot find module '../BargingToggleButton'".

- [ ] **Step 3: Implement the component**

Create `frontend/src/features/chat/cockpit/buttons/BargingToggleButton.tsx`:

```tsx
import type { ReactNode } from 'react'
import { useBargeSettingsStore } from '@/features/voice/stores/bargeSettingsStore'
import { usePhase } from '@/features/voice/usePhase'

/**
 * Toggle button for the barging preference. Visible in the cockpit
 * only while live voice mode is active (sibling components decide
 * the visibility — this component renders unconditionally when
 * mounted).
 *
 * Three visual states:
 *   - on:                open-lips, green, no pulse
 *   - off + not speaking: lips-with-slash, red, no pulse
 *   - off + speaking:     mic-with-slash, red, slow pulse ('Sendepause')
 *
 * The mic-with-slash glyph during persona speech is the explicit cue
 * that the user's voice input is currently being held back. The
 * glyph swap (lips → mic) makes the cue semantically direct without
 * adding a second slash to the existing blue VoiceButton.
 *
 * See devdocs/specs/2026-05-07-barging-toggle-design.md.
 */
export function BargingToggleButton() {
  const enabled = useBargeSettingsStore((s) => s.enabled)
  const toggle = useBargeSettingsStore((s) => s.toggle)
  const phase = usePhase()

  const isSpeaking = phase === 'speaking'

  let state: 'on' | 'off-idle' | 'off-speaking'
  let glyph: ReactNode
  let title: string

  if (enabled) {
    state = 'on'
    glyph = <LipsOpenIcon />
    title = 'You can interrupt the persona while she speaks'
  } else if (isSpeaking) {
    state = 'off-speaking'
    glyph = <MicSlashIcon />
    title = "Mic asleep while persona speaks — tap to enable"
  } else {
    state = 'off-idle'
    glyph = <LipsSlashIcon />
    title = "Persona speech can't be interrupted — tap to enable"
  }

  const colourClass = enabled
    ? 'text-[#4ade80] border-[#22c55e]/35 bg-[#22c55e]/15'
    : 'text-[#ef4444] border-[#dc2626]/35 bg-[#dc2626]/15'

  const pulseClass = state === 'off-speaking' ? 'animate-pulse-slow' : ''

  const className = [
    'cockpit-btn-fixed inline-flex items-center justify-center rounded-md border transition',
    colourClass,
    pulseClass,
  ].filter(Boolean).join(' ')

  return (
    <button
      type="button"
      onClick={toggle}
      title={title}
      aria-label={title}
      aria-pressed={!enabled}
      data-barge-state={state}
      className={className}
    >
      {glyph}
    </button>
  )
}

function LipsOpenIcon() {
  return (
    <svg
      data-glyph="lips-open"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <ellipse cx="8" cy="8" rx="5" ry="2.6" />
      <path d="M3 8H13" strokeWidth="1.1" opacity="0.55" />
    </svg>
  )
}

function LipsSlashIcon() {
  return (
    <svg
      data-glyph="lips-slash"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <ellipse cx="8" cy="8" rx="5" ry="2.6" />
      <path d="M3 8H13" strokeWidth="1.1" opacity="0.55" />
      <path d="M2 14 L14 2" strokeWidth="1.6" />
    </svg>
  )
}

function MicSlashIcon() {
  return (
    <svg
      data-glyph="mic-slash"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <rect x="6" y="2" width="4" height="7" rx="2" fill="currentColor" />
      <path
        d="M4 7.5V8a4 4 0 0 0 8 0v-.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <path d="M8 12v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M5.5 14h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path
        d="M2 2 14 14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter ./frontend test BargingToggleButton`
Expected: all 5 tests PASS.

- [ ] **Step 5: Build check**

Run: `pnpm --filter ./frontend run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/BargingToggleButton.tsx \
        frontend/src/features/chat/cockpit/buttons/__tests__/BargingToggleButton.test.tsx
git commit -m "$(cat <<'EOF'
Add BargingToggleButton with three visual states

Lips-open green when on. Lips-with-slash red statically when off and
not speaking. Mic-with-slash red with slow pulse when off and the
persona is currently speaking — the explicit 'Sendepause' cue.

Self-contained component (not CockpitButton-based), since the existing
CockpitButton accent palette has no red.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire the gate into useConversationMode

**Files:**
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts`

This task has no new unit test of its own — the gate's logic is fully
covered by `bargeGate.test.ts`, and the wiring change is a single
short-circuit. The behavioural integration is exercised by the manual
verification steps at the end of this plan.

- [ ] **Step 1: Add the imports**

In `frontend/src/features/voice/hooks/useConversationMode.ts`, add to
the existing import block at the top of the file:

```ts
import { useBargeSettingsStore } from '../stores/bargeSettingsStore'
import { shouldSuppressBarge } from '../bargeGate'
import { getActiveGroup } from '../../chat/responseTaskGroup'
```

(`getActiveGroup` may already be imported transitively elsewhere; if a
duplicate import is detected, do not add a second one.)

- [ ] **Step 2: Extend the micMuted short-circuit in handleSpeechStart**

Locate the block at `frontend/src/features/voice/hooks/useConversationMode.ts:431-434`:

```ts
    if (micMutedRef.current) {
      utteranceStartedWhileMutedRef.current = true
      return
    }
    utteranceStartedWhileMutedRef.current = false
```

Replace it with:

```ts
    // Two reasons to behave as if the mic were muted: the user has
    // explicitly muted it, OR the user has barging turned off and the
    // persona is currently speaking. Both paths share the same effect:
    // VAD keeps running for the indicator, but no barge fires, no
    // utterance is recorded, and no STT pipeline is triggered.
    const bargeSuppressed = shouldSuppressBarge({
      enabled: useBargeSettingsStore.getState().enabled,
      groupState: getActiveGroup()?.state ?? null,
    })
    if (micMutedRef.current || bargeSuppressed) {
      utteranceStartedWhileMutedRef.current = true
      if (bargeSuppressed && !micMutedRef.current) {
        console.info('[BargeGate] suppressed VAD onset', {
          groupState: getActiveGroup()?.state,
          bargingEnabled: false,
        })
      }
      return
    }
    utteranceStartedWhileMutedRef.current = false
```

- [ ] **Step 3: Build check**

Run: `pnpm --filter ./frontend run build`
Expected: build succeeds, no type errors.

- [ ] **Step 4: Run all voice tests to ensure nothing regressed**

Run: `pnpm --filter ./frontend test src/features/voice/`
Expected: all existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/hooks/useConversationMode.ts
git commit -m "$(cat <<'EOF'
Suppress barge VAD onsets in useConversationMode when barging is off

Extends the existing micMuted short-circuit in handleSpeechStart with
the same effect when shouldSuppressBarge returns true. Logs a single
[BargeGate] line so testers can distinguish gate-eaten attempts from
STT/network issues.

In-flight barges are not aborted: the gate sits before bargeController
.start, so existing barges run to their natural terminal state. Only
future VAD onsets while barging-off + speaking are suppressed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Cockpit slot integration

**Files:**
- Modify: `frontend/src/features/chat/cockpit/CockpitBar.tsx`

- [ ] **Step 1: Import the new button and read live state**

In `frontend/src/features/chat/cockpit/CockpitBar.tsx`, add to the
existing imports:

```tsx
import { BargingToggleButton } from './buttons/BargingToggleButton'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
```

Inside `CockpitBar(props)`, near the existing `useViewport()` call, add:

```tsx
  const liveActive = useConversationModeStore((s) => s.active)
```

- [ ] **Step 2: Mobile slot — replace ⓘ when liveActive**

Locate the mobile-only block at `CockpitBar.tsx:152-160`:

```tsx
      {isMobile && (
        <CockpitButton
          icon="ⓘ"
          state="idle"
          accent="neutral"
          label="Status info"
          onClick={() => setInfoOpen(true)}
        />
      )}
```

Replace with:

```tsx
      {isMobile && (
        liveActive ? (
          <BargingToggleButton />
        ) : (
          <CockpitButton
            icon="ⓘ"
            state="idle"
            accent="neutral"
            label="Status info"
            onClick={() => setInfoOpen(true)}
          />
        )
      )}
```

- [ ] **Step 3: Desktop slot — append separator + toggle when liveActive**

Locate the LiveButton block at `CockpitBar.tsx:138-142`:

```tsx
      <LiveButton
        sessionId={props.sessionId}
        canEnterLive={props.liveAvailability.canEnterLive}
        disabledReason={props.liveAvailability.reason}
      />
```

Immediately after this block (before the `{isMobile && (` for the emoji
button on the next line), insert:

```tsx
      {!isMobile && liveActive && (
        <>
          <Sep />
          <BargingToggleButton />
        </>
      )}
```

- [ ] **Step 4: Build check**

Run: `pnpm --filter ./frontend run build`
Expected: build succeeds.

- [ ] **Step 5: Run cockpit-related tests**

Run: `pnpm --filter ./frontend test src/features/chat/cockpit`
Expected: existing tests still pass (no regression in CockpitBar or
related buttons).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/cockpit/CockpitBar.tsx
git commit -m "$(cat <<'EOF'
Render BargingToggleButton in cockpit while live voice is active

Mobile: replace the (i) info button with the toggle when liveActive.
Desktop: append a separator and the toggle after the Live button when
liveActive. Out of live mode, both layouts are unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Manual verification on real device

This task is **not** delegatable to a subagent — Chris runs it himself
on real desktop and mobile devices. Each step assumes the dev server
is running locally.

- [ ] **Step 1: Mobile slot swap visible**

On mobile viewport (or DevTools device emulation): open a chat session
with a voice-capable persona. Confirm the cockpit shows `ⓘ` at the
right end. Tap the Live button (🎙) to enter live voice mode. Confirm
`ⓘ` is replaced by the new BargingToggle (open-lips, green, since
default is on). Tap Live again to leave live mode. Confirm `ⓘ` is
back.

- [ ] **Step 2: Desktop slot append visible**

On desktop (≥ 1024px): same persona. Enter live voice mode. Confirm a
separator (`│`) and the BargingToggle appear after the Live button.
Leave live mode. Confirm both vanish, no leftover separator.

- [ ] **Step 3: Barging on, normal interruption works**

In live mode with toggle on (green): start a chat that triggers a long
persona response. While the persona is speaking, speak over her at
normal volume. Confirm the existing barge behaviour: persona pauses,
your speech is transcribed, a new turn starts.

- [ ] **Step 4: Barging off, persona continues uninterrupted**

Tap the toggle to switch off (red, lips-with-slash). Trigger another
long persona response. While she is speaking, speak over her. Confirm:
persona keeps speaking, no barge fires, the toggle has swapped to the
mic-with-slash glyph and is pulsing slowly. Open the browser console
and confirm `[BargeGate] suppressed VAD onset` log lines appear when
you speak.

- [ ] **Step 5: Mid-speak toggle off → on**

While the persona is mid-response with barging off (toggle pulsing):
tap the toggle to enable. Now speak. Confirm a normal barge fires
(persona pauses, your speech transcribed).

- [ ] **Step 6: Mid-barge toggle off does not abort the in-flight barge**

With barging on, trigger a long persona response. While she speaks,
start speaking yourself (a barge enters `pending-stt`). **Immediately**
tap the toggle to off. Confirm: your in-flight barge completes
normally — your sentence is transcribed and sent. Now during the
*next* persona response, speak again — confirm this attempt is
suppressed.

- [ ] **Step 7: Persistence across reload**

Set toggle to off. Reload the page. Re-enter live mode. Confirm the
toggle is still off (red, lips-with-slash) — read from localStorage.

- [ ] **Step 8: Default on a fresh profile**

Open the app in a fresh browser profile or incognito window. Enter
live mode. Confirm the toggle is on (green, lips-open) — default
applies.

- [ ] **Step 9: Reduced-motion is honoured**

Enable `prefers-reduced-motion: reduce` in the OS or via DevTools
("Emulate CSS media feature prefers-reduced-motion"). Trigger barging
off + speaking. Confirm: the colour and glyph still convey the state
(red, mic-with-slash), but the pulsation is suppressed by the
`animate-pulse-slow` Tailwind utility (which already respects the
media query).

  *Note: `animate-pulse-slow` should already be reduced-motion aware
  via Tailwind's default reduced-motion support. If pulsation is NOT
  suppressed, confirm whether `tailwind.config` has a reduced-motion
  override and add one if missing.*

- [ ] **Step 10: Final commit (only if any small fixups were needed)**

If the manual run-through revealed minor cosmetic fixups (alignment,
spacing, glyph-size tweak), commit them with a separate small commit:

```bash
git add <files>
git commit -m "Polish barging toggle: <one-line description>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-review checklist (run by the planner before handoff)

This section is for the planner — not a step a subagent runs.

**Spec coverage:**

- §UI / Placement → Task 5
- §UI / Visual states → Task 3 (component) + Task 1 (state) + Task 4 (gate behaviour during speaking)
- §UI / Tooltips → Task 3 (titles match the three states)
- §UI / Mic-Button unchanged → covered by *not* touching `VoiceButton.tsx`
- §State / Storage → Task 1
- §State / Default → Task 1 (test case)
- §State / Lifetime (not reset on exit) → Task 1 (separate store, not coupled to conversationModeStore.exit())
- §Behaviour / The gate → Task 2 (pure function) + Task 4 (wiring)
- §Behaviour / Mid-speak Option 3 → covered by Task 4 (gate sits before `start()`, so in-flight barges are untouched)
- §Behaviour / Logging → Task 4
- §Testing / Three new unit tests → Task 1 (4 tests) + Task 2 (4 tests) + Task 3 (5 tests). The original spec asked for three unit tests; this plan delivers more in-depth pure-function coverage of the gate logic, which is structurally simpler than mounting the full hook. The mid-barge case from the spec's test 3 maps to manual verification Step 6 since it exercises real STT timing.
- §Testing / Manual verification → Task 6

**Placeholder scan:**

- No "TBD" / "TODO" left.
- All commit messages are concrete.
- All file paths are absolute relative to the repo root.
- All test code is complete.
- All implementation code is complete.

**Type consistency:**

- `BargeSettingsState` interface matches across the store and its tests.
- `ShouldSuppressBargeInput.groupState` uses `ResponseTaskGroup['state'] | null`, which matches `derivePhase.ts:39`.
- `data-barge-state` values: `'on'`, `'off-idle'`, `'off-speaking'` — three values, used identically in the component and the tests.
- `data-glyph` values: `'lips-open'`, `'lips-slash'`, `'mic-slash'` — three values, used identically.

No drift detected.
