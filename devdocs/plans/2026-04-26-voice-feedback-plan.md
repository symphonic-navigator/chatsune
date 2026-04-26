# Voice Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mic-activity pulse to the LiveButton and a tap-to-pause hit-strip on the spectrum visualiser; pause auto-mutes the mic in Live mode and resume restores the previous state.

**Architecture:** Frontend-only. Two new modules (`micActivity` emitter, `visualiserPauseStore`), one new overlay component (`VoiceVisualiserHitStrip`), and surgical extensions to `audioPlayback`, `useConversationMode`, `LiveButton`, `CockpitButton`, `VoiceVisualiser`, `useTtsFrequencyData`. State auto-heals via the existing `audioPlayback.subscribe()` mechanism on idle transitions.

**Tech Stack:** React 18 + TypeScript + Zustand + Vite + Vitest + React Testing Library + Tailwind. No backend, no DTOs.

**Spec:** `devdocs/specs/2026-04-26-voice-feedback-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `frontend/src/features/voice/infrastructure/audioPlayback.ts` | modify | add `isActive()` getter (true during play OR pause OR queued) |
| `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts` | modify | add `isActive()` test cases |
| `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts` | modify | use `isActive()` instead of `isPlaying()` so bars stay visible during pause |
| `frontend/src/features/voice/infrastructure/micActivity.ts` | create | singleton emitter for mic RMS level + VAD edge state |
| `frontend/src/features/voice/infrastructure/__tests__/micActivity.test.ts` | create | unit tests for the emitter |
| `frontend/src/features/voice/hooks/useConversationMode.ts` | modify | wire `onVolumeChange` and VAD callbacks to `micActivity` |
| `frontend/src/features/chat/cockpit/CockpitButton.tsx` | modify | accept optional `buttonRef` prop forwarded to inner `<button>` |
| `frontend/src/features/chat/cockpit/buttons/LiveButton.tsx` | modify | own RAF loop, write transform/box-shadow on the button DOM node from `micActivity` data |
| `frontend/src/features/voice/stores/visualiserPauseStore.ts` | create | `paused` + `mutedByPause` state + `togglePause()` + module-init auto-clear |
| `frontend/src/features/voice/stores/__tests__/visualiserPauseStore.test.ts` | create | toggle flows, auto-clear on idle, mic restoration |
| `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx` | create | invisible accessible button overlay covering centre 30vh |
| `frontend/src/features/voice/components/__tests__/VoiceVisualiserHitStrip.test.tsx` | create | conditional rendering + click toggles store |
| `frontend/src/app/layouts/AppLayout.tsx` | modify | mount `<VoiceVisualiserHitStrip />` next to `<VoiceVisualiser />` |
| `frontend/src/features/voice/components/VoiceVisualiser.tsx` | modify | freeze bars via snapshot + breathing opacity when `paused` |

---

## Task 1: Add `audioPlayback.isActive()` accessor

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts:247`
- Test: `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`

`isPlaying()` only returns true while a source is actively playing. Pause sets `playing=false, paused=true`. We need a method that stays true across pause and queue-non-empty so the hit-strip and visualiser keep their state during a pause.

- [ ] **Step 1: Write the failing tests**

Append a new `describe` block at the end of `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts` (the file already contains multiple top-level `describe` blocks, e.g. `audioPlayback — pause/resume`, `audioPlayback — subscribe API` — follow the same pattern):

```ts
describe('audioPlayback — isActive()', () => {
  it('returns false when idle', () => {
    expect(audioPlayback.isActive()).toBe(false)
  })

  it('returns true while playing', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(24_000), SEGMENT)
    expect(audioPlayback.isActive()).toBe(true)
  })

  it('returns true while paused mid-playback', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(24_000), SEGMENT)
    audioPlayback.pause()
    expect(audioPlayback.isActive()).toBe(true)
  })

  it('returns true when only queue has entries (between segments)', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn(), gapMs: 50 })
    audioPlayback.enqueue(new Float32Array(24_000), SEGMENT)
    audioPlayback.enqueue(new Float32Array(24_000), SEGMENT)
    // End first segment; gap timer arms — playing=false, queue.length>0
    sources[0].onended?.()
    expect(audioPlayback.isActive()).toBe(true)
  })

  it('returns false after stopAll()', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(24_000), SEGMENT)
    audioPlayback.stopAll()
    expect(audioPlayback.isActive()).toBe(false)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
```

Expected: 5 new tests fail with `audioPlayback.isActive is not a function`.

- [ ] **Step 3: Implement the `isActive()` method**

Edit `frontend/src/features/voice/infrastructure/audioPlayback.ts`. Replace the line:

```ts
  isPlaying(): boolean { return this.playing }
```

with:

```ts
  isPlaying(): boolean { return this.playing }

  /**
   * True whenever there is *something* the playback pipeline is responsible
   * for: an actively playing source, a paused-but-resumable session, or
   * pending entries in the queue. Used by overlays (visualiser, hit-strip)
   * that must stay visible across the entire active lifecycle, including
   * the gap between two segments and the paused-but-not-cancelled state.
   */
  isActive(): boolean {
    return this.playing || this.paused || this.queue.length > 0
  }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioPlayback.ts \
        frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
git commit -m "Add audioPlayback.isActive() covering play, pause, queued"
```

---

## Task 2: Update `useTtsFrequencyData` to use `isActive()`

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts:76`

The visualiser fades bars to invisible when `accessors.isActive()` returns false. With `isPlaying()` it would fade during pause — we want the bars to stay visible (frozen + breathing).

- [ ] **Step 1: Make the swap**

In `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts`, change:

```ts
      isActive: () => audioPlayback.isPlaying(),
```

to:

```ts
      isActive: () => audioPlayback.isActive(),
```

- [ ] **Step 2: Run the visualiser-related tests and the type check**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/
cd frontend && pnpm test --run src/features/voice/__tests__/
```

Expected: no type errors, all tests still pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts
git commit -m "useTtsFrequencyData: use isActive so bars stay visible during pause"
```

---

## Task 3: Create the `micActivity` singleton

**Files:**
- Create: `frontend/src/features/voice/infrastructure/micActivity.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/micActivity.test.ts`

A small subscribable singleton. Hot path is `setLevel()`, called every frame from `audioCapture`'s volume meter.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/voice/infrastructure/__tests__/micActivity.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { micActivity } from '../micActivity'

describe('micActivity', () => {
  beforeEach(() => {
    micActivity.setLevel(0)
    micActivity.setVadActive(false)
  })

  it('starts at zero level and inactive VAD', () => {
    expect(micActivity.getLevel()).toBe(0)
    expect(micActivity.getVadActive()).toBe(false)
  })

  it('setLevel updates the level', () => {
    micActivity.setLevel(0.42)
    expect(micActivity.getLevel()).toBe(0.42)
  })

  it('setVadActive toggles the flag', () => {
    micActivity.setVadActive(true)
    expect(micActivity.getVadActive()).toBe(true)
    micActivity.setVadActive(false)
    expect(micActivity.getVadActive()).toBe(false)
  })

  it('subscribe fires on setLevel changes', () => {
    const listener = vi.fn()
    const unsub = micActivity.subscribe(listener)
    micActivity.setLevel(0.5)
    micActivity.setLevel(0.7)
    expect(listener).toHaveBeenCalledTimes(2)
    unsub()
  })

  it('subscribe fires on setVadActive transitions only', () => {
    const listener = vi.fn()
    const unsub = micActivity.subscribe(listener)
    micActivity.setVadActive(true)
    micActivity.setVadActive(true)   // identical → no notify
    micActivity.setVadActive(false)
    expect(listener).toHaveBeenCalledTimes(2)
    unsub()
  })

  it('unsubscribe stops further notifications', () => {
    const listener = vi.fn()
    const unsub = micActivity.subscribe(listener)
    micActivity.setLevel(0.1)
    unsub()
    micActivity.setLevel(0.2)
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('listener errors do not break the emitter loop', () => {
    const bad = vi.fn(() => { throw new Error('boom') })
    const good = vi.fn()
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    micActivity.subscribe(bad)
    micActivity.subscribe(good)
    micActivity.setLevel(0.5)
    expect(good).toHaveBeenCalledTimes(1)
    errSpy.mockRestore()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/micActivity.test.ts
```

Expected: tests fail because the file doesn't exist yet.

- [ ] **Step 3: Implement the singleton**

Create `frontend/src/features/voice/infrastructure/micActivity.ts`:

```ts
type MicActivityListener = () => void

class MicActivityImpl {
  private level = 0
  private vadActive = false
  private listeners = new Set<MicActivityListener>()

  /** Hot path: called per frame from audioCapture's volume meter. */
  setLevel(value: number): void {
    this.level = value
    this.notify()
  }

  /** Edge-trigger only: notify on actual transitions. */
  setVadActive(value: boolean): void {
    if (this.vadActive === value) return
    this.vadActive = value
    this.notify()
  }

  getLevel(): number { return this.level }
  getVadActive(): boolean { return this.vadActive }

  subscribe(listener: MicActivityListener): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private notify(): void {
    for (const l of this.listeners) {
      try { l() } catch (err) {
        console.error('[micActivity] Listener threw:', err)
      }
    }
  }
}

export const micActivity = new MicActivityImpl()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/micActivity.test.ts
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/micActivity.ts \
        frontend/src/features/voice/infrastructure/__tests__/micActivity.test.ts
git commit -m "Add micActivity singleton for live mic level and VAD state"
```

---

## Task 4: Wire `useConversationMode` to `micActivity`

**Files:**
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts:528` (`onVolumeChange`)
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts` (handleSpeechStart, handleSpeechEnd, handleMisfire, teardown)

The current `onVolumeChange: () => {}` discards the level. Wire it to `micActivity.setLevel`. Mirror the existing VAD edge calls (`setVadActive(...)` on the conversation-mode store) to `micActivity.setVadActive(...)` so the LiveButton has a phase-independent signal.

- [ ] **Step 1: Read the current file**

Read `frontend/src/features/voice/hooks/useConversationMode.ts` and locate:
- The import block at the top (we need to add the `micActivity` import)
- `handleSpeechStart` — fires `setVadActive(true)`
- `handleSpeechEnd` — fires `setVadActive(false)`
- `handleMisfire` — fires `setVadActive(false)`
- `teardown` — clears state on exit
- The `audioCapture.startContinuous(...)` call site at line 525 with `onVolumeChange: () => {}` at line 528

- [ ] **Step 2: Add the import**

Add to the imports near the top of the file:

```ts
import { micActivity } from '../infrastructure/micActivity'
```

- [ ] **Step 3: Replace the no-op `onVolumeChange`**

In the `audioCapture.startContinuous(...)` call (line 525-ish), change:

```ts
        onVolumeChange: () => {},
```

to:

```ts
        onVolumeChange: (level) => micActivity.setLevel(level),
```

- [ ] **Step 4: Mirror VAD edges to micActivity**

In `handleSpeechStart` (after the existing `setVadActive(true)` call), add:

```ts
    micActivity.setVadActive(true)
```

In `handleSpeechEnd` (after the existing `setVadActive(false)` call), add:

```ts
    micActivity.setVadActive(false)
```

In `handleMisfire` (after the existing `setVadActive(false)` call), add:

```ts
    micActivity.setVadActive(false)
```

In the `teardown` callback (where `setVadActive(false)` is called on store exit), add:

```ts
    micActivity.setLevel(0)
    micActivity.setVadActive(false)
```

- [ ] **Step 5: Verify the build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm test --run src/features/voice/
```

Expected: no type errors, all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/hooks/useConversationMode.ts
git commit -m "Wire useConversationMode mic level and VAD edges to micActivity"
```

---

## Task 5: Add `buttonRef` prop to `CockpitButton`

**Files:**
- Modify: `frontend/src/features/chat/cockpit/CockpitButton.tsx`

LiveButton needs direct DOM access to the inner `<button>` to mutate its style each frame without re-rendering. Add an optional ref prop.

- [ ] **Step 1: Update the Props type and forward the ref**

In `frontend/src/features/chat/cockpit/CockpitButton.tsx`, change the `Props` type:

```ts
type Props = {
  icon: ReactNode
  state: CockpitButtonState
  accent?: 'gold' | 'blue' | 'purple' | 'green' | 'neutral'
  label: string
  panel?: ReactNode
  onClick?: () => void
  ariaLabel?: string
  /** Optional ref forwarded to the inner <button>. Used for low-frequency
   *  imperative DOM updates (e.g. CSS transform driven by an external RAF). */
  buttonRef?: React.Ref<HTMLButtonElement>
}
```

In the function signature, destructure the new prop:

```ts
export function CockpitButton({
  icon, state, accent = 'neutral', label, panel, onClick, ariaLabel, buttonRef,
}: Props) {
```

In the rendered `<button>`, attach the ref:

```tsx
      <button
        type="button"
        ref={buttonRef}
        disabled={!actionable}
        aria-label={ariaLabel ?? label}
        title={label}
        className={classes}
        onClick={onClick}
      >
        {icon}
      </button>
```

- [ ] **Step 2: Verify the build**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/cockpit/CockpitButton.tsx
git commit -m "CockpitButton: accept optional buttonRef forwarded to inner button"
```

---

## Task 6: Implement LiveButton pulse

**Files:**
- Modify: `frontend/src/features/chat/cockpit/buttons/LiveButton.tsx`

Add a RAF-driven pulse that reads from `micActivity` and writes inline `transform` + `box-shadow` on the button DOM. Subtle hybrid: small pulse from raw RMS, strong pulse when `vadActive`.

- [ ] **Step 1: Add imports and refs**

At the top of `frontend/src/features/chat/cockpit/buttons/LiveButton.tsx`, add:

```ts
import { useEffect, useRef } from 'react'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { micActivity } from '@/features/voice/infrastructure/micActivity'
```

(Keep the existing imports; `useConversationModeStore` and `stopActiveReadAloud` should already be there. Add `useEffect`, `useRef`, and `micActivity`.)

Inside the `LiveButton` component function, after the existing hook calls, add:

```ts
  const micMuted = useConversationModeStore((s) => s.micMuted)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const pulseRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const reducedMotionRef = useRef(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotionRef.current = mq.matches
    const listener = () => { reducedMotionRef.current = mq.matches }
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  useEffect(() => {
    const enabled = active && !micMuted && !reducedMotionRef.current
    if (!enabled) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      pulseRef.current = 0
      const el = buttonRef.current
      if (el) {
        el.style.transform = ''
        el.style.boxShadow = ''
        el.style.transition = ''
      }
      return
    }

    const tick = () => {
      const level = micActivity.getLevel()
      const vad = micActivity.getVadActive()
      const target = vad
        ? Math.min(1, level * 2.5)
        : Math.min(0.4, level * 1.5)
      pulseRef.current += (target - pulseRef.current) * 0.18

      const el = buttonRef.current
      if (el) {
        const p = pulseRef.current
        el.style.transform = `scale(${(1 + p * 0.12).toFixed(3)})`
        el.style.boxShadow = `0 0 ${(p * 18).toFixed(2)}px rgba(74, 222, 128, ${(p * 0.6).toFixed(3)})`
        el.style.transition = 'transform 60ms linear, box-shadow 60ms linear'
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const el = buttonRef.current
      if (el) {
        el.style.transform = ''
        el.style.boxShadow = ''
        el.style.transition = ''
      }
    }
  }, [active, micMuted])
```

- [ ] **Step 2: Pass `buttonRef` to CockpitButton**

In the rendered `<CockpitButton ... />` JSX, add the prop:

```tsx
    <CockpitButton
      icon="🎙"
      state={active ? 'active' : 'idle'}
      accent="green"
      label={active ? 'Voice chat · on' : 'Voice chat · off'}
      onClick={handleClick}
      buttonRef={buttonRef}
      panel={...}
    />
```

(Add `buttonRef={buttonRef}` to the existing JSX without otherwise changing it.)

- [ ] **Step 3: Verify the build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm test --run src/features/chat/cockpit/
```

Expected: no type errors, no test failures.

- [ ] **Step 4: Manual smoke check**

```bash
cd frontend && pnpm dev
```

In the browser:
- Open a chat session with a Live-capable persona.
- Click LiveButton (🎙) to enter Live mode.
- Speak softly into the mic — observe a small pulse on the button.
- Speak loudly — observe a strong pulse.
- Click the cockpit Voice button to mute the mic — pulse stops, button settles to its plain green-active state.
- Click again to unmute — pulse responds to speech again.
- Exit Live mode — pulse stops, button returns to idle (green-off).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/LiveButton.tsx
git commit -m "LiveButton: pulse on mic activity (hybrid RMS + VAD)"
```

---

## Task 7: Create `visualiserPauseStore` + tests

**Files:**
- Create: `frontend/src/features/voice/stores/visualiserPauseStore.ts`
- Create: `frontend/src/features/voice/stores/__tests__/visualiserPauseStore.test.ts`

A small Zustand store with `paused: boolean`, `mutedByPause: boolean`, `togglePause()`, plus a module-init subscription to `audioPlayback` for auto-clearing on idle transitions.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/voice/stores/__tests__/visualiserPauseStore.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock audioPlayback BEFORE the store is imported, since the store wires
// a module-init subscription on first import.
const audioPlaybackMock = {
  pause: vi.fn(),
  resume: vi.fn(),
  isActive: vi.fn(() => true),
  subscribe: vi.fn((_listener: () => void) => () => {}),
}
vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: audioPlaybackMock,
}))

// Mock conversationModeStore so togglePause can read/write mic state.
const cmState = {
  active: false,
  micMuted: false,
  setMicMuted: vi.fn((value: boolean) => { cmState.micMuted = value }),
}
vi.mock('../conversationModeStore', () => ({
  useConversationModeStore: {
    getState: () => cmState,
  },
}))

let useVisualiserPauseStore: typeof import('../visualiserPauseStore').useVisualiserPauseStore
let subscribedListener: (() => void) | null = null

describe('visualiserPauseStore', () => {
  beforeEach(async () => {
    vi.resetModules()
    audioPlaybackMock.pause.mockClear()
    audioPlaybackMock.resume.mockClear()
    audioPlaybackMock.isActive.mockReset().mockReturnValue(true)
    audioPlaybackMock.subscribe.mockReset().mockImplementation((listener: () => void) => {
      subscribedListener = listener
      return () => { subscribedListener = null }
    })
    cmState.active = false
    cmState.micMuted = false
    cmState.setMicMuted.mockClear()
    subscribedListener = null
    const mod = await import('../visualiserPauseStore')
    useVisualiserPauseStore = mod.useVisualiserPauseStore
    useVisualiserPauseStore.setState({ paused: false, mutedByPause: false })
  })

  it('starts unpaused', () => {
    const s = useVisualiserPauseStore.getState()
    expect(s.paused).toBe(false)
    expect(s.mutedByPause).toBe(false)
  })

  it('togglePause in normal mode pauses TTS without touching the mic', () => {
    cmState.active = false
    useVisualiserPauseStore.getState().togglePause()
    expect(audioPlaybackMock.pause).toHaveBeenCalledOnce()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().paused).toBe(true)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('togglePause in Live mode with mic on mutes the mic and records the flag', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()
    expect(cmState.setMicMuted).toHaveBeenCalledWith(true)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(true)
  })

  it('togglePause in Live mode with mic already muted does NOT record the flag', () => {
    cmState.active = true
    cmState.micMuted = true
    useVisualiserPauseStore.getState().togglePause()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('togglePause when already paused resumes and unmutes if we muted', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()  // pause
    cmState.setMicMuted.mockClear()
    useVisualiserPauseStore.getState().togglePause()  // resume
    expect(audioPlaybackMock.resume).toHaveBeenCalledOnce()
    expect(cmState.setMicMuted).toHaveBeenCalledWith(false)
    expect(useVisualiserPauseStore.getState().paused).toBe(false)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('togglePause resume does NOT unmute if we did not mute', () => {
    cmState.active = true
    cmState.micMuted = true
    useVisualiserPauseStore.getState().togglePause()  // pause; mutedByPause=false
    cmState.setMicMuted.mockClear()
    useVisualiserPauseStore.getState().togglePause()  // resume
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
  })

  it('auto-clear: idle transition clears paused and restores mic if muted by us', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()
    expect(useVisualiserPauseStore.getState().paused).toBe(true)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(true)

    audioPlaybackMock.isActive.mockReturnValue(false)
    cmState.setMicMuted.mockClear()
    subscribedListener?.()

    expect(cmState.setMicMuted).toHaveBeenCalledWith(false)
    expect(useVisualiserPauseStore.getState().paused).toBe(false)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('auto-clear: idle transition while NOT paused is a no-op', () => {
    audioPlaybackMock.isActive.mockReturnValue(false)
    subscribedListener?.()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().paused).toBe(false)
  })

  it('auto-clear: still active → no-op', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()
    audioPlaybackMock.isActive.mockReturnValue(true)
    cmState.setMicMuted.mockClear()
    subscribedListener?.()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().paused).toBe(true)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test --run src/features/voice/stores/__tests__/visualiserPauseStore.test.ts
```

Expected: tests fail because the store file doesn't exist.

- [ ] **Step 3: Implement the store**

Create `frontend/src/features/voice/stores/visualiserPauseStore.ts`:

```ts
import { create } from 'zustand'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { useConversationModeStore } from './conversationModeStore'

interface VisualiserPauseState {
  paused: boolean
  /** Whether the togglePause path muted the mic (so resume should unmute it). */
  mutedByPause: boolean
  togglePause: () => void
}

export const useVisualiserPauseStore = create<VisualiserPauseState>((set, get) => ({
  paused: false,
  mutedByPause: false,

  togglePause: () => {
    const { paused, mutedByPause } = get()
    if (!paused) {
      audioPlayback.pause()
      const cm = useConversationModeStore.getState()
      if (cm.active && !cm.micMuted) {
        cm.setMicMuted(true)
        set({ paused: true, mutedByPause: true })
      } else {
        set({ paused: true, mutedByPause: false })
      }
    } else {
      audioPlayback.resume()
      if (mutedByPause) {
        useConversationModeStore.getState().setMicMuted(false)
      }
      set({ paused: false, mutedByPause: false })
    }
  },
}))

// Auto-clear on idle: when audioPlayback transitions from active to idle
// (Cockpit-Stop, Group cancelled, queue drained, Live-mode exited), drop
// the pause state and restore the mic if we muted it. The subscription is
// established once at module import time and lives for the app lifetime.
audioPlayback.subscribe(() => {
  if (audioPlayback.isActive()) return
  const { paused, mutedByPause } = useVisualiserPauseStore.getState()
  if (!paused) return
  if (mutedByPause) {
    useConversationModeStore.getState().setMicMuted(false)
  }
  useVisualiserPauseStore.setState({ paused: false, mutedByPause: false })
})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test --run src/features/voice/stores/__tests__/visualiserPauseStore.test.ts
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/stores/visualiserPauseStore.ts \
        frontend/src/features/voice/stores/__tests__/visualiserPauseStore.test.ts
git commit -m "Add visualiserPauseStore with togglePause and idle auto-clear"
```

---

## Task 8: Create `VoiceVisualiserHitStrip` + tests

**Files:**
- Create: `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`
- Create: `frontend/src/features/voice/components/__tests__/VoiceVisualiserHitStrip.test.tsx`

Invisible accessible button overlay. Renders only while: visualiser is enabled, TTS is active (or paused), `prefers-reduced-motion: reduce` is not set. Click invokes `togglePause`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/voice/components/__tests__/VoiceVisualiserHitStrip.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

const audioPlaybackMock = {
  isActive: vi.fn(() => false),
  subscribe: vi.fn((_listener: () => void) => () => {}),
}
vi.mock('@/features/voice/infrastructure/audioPlayback', () => ({
  audioPlayback: audioPlaybackMock,
}))

const settingsState = { visualisation: { enabled: true } }
vi.mock('@/features/voice/stores/voiceSettingsStore', () => ({
  useVoiceSettingsStore: <T,>(selector: (s: typeof settingsState) => T) => selector(settingsState),
}))

const pauseState = { paused: false, mutedByPause: false }
const togglePauseMock = vi.fn(() => { pauseState.paused = !pauseState.paused })
vi.mock('@/features/voice/stores/visualiserPauseStore', () => ({
  useVisualiserPauseStore: <T,>(selector: (s: { paused: boolean; togglePause: () => void }) => T) =>
    selector({ paused: pauseState.paused, togglePause: togglePauseMock }),
}))

let mqMatches = false
let mqListener: ((e: { matches: boolean }) => void) | null = null

beforeEach(() => {
  audioPlaybackMock.isActive.mockReset().mockReturnValue(false)
  audioPlaybackMock.subscribe.mockReset().mockImplementation(() => () => {})
  settingsState.visualisation.enabled = true
  pauseState.paused = false
  togglePauseMock.mockClear()
  mqMatches = false
  mqListener = null
  vi.stubGlobal('matchMedia', (_q: string) => ({
    matches: mqMatches,
    addEventListener: (_t: string, l: (e: { matches: boolean }) => void) => { mqListener = l },
    removeEventListener: () => { mqListener = null },
  }))
})

import { VoiceVisualiserHitStrip } from '../VoiceVisualiserHitStrip'

describe('VoiceVisualiserHitStrip', () => {
  it('renders nothing when visualiser is disabled', () => {
    settingsState.visualisation.enabled = false
    audioPlaybackMock.isActive.mockReturnValue(true)
    const { container } = render(<VoiceVisualiserHitStrip />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when reduced motion is set', () => {
    mqMatches = true
    audioPlaybackMock.isActive.mockReturnValue(true)
    const { container } = render(<VoiceVisualiserHitStrip />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when audio is idle and not paused', () => {
    audioPlaybackMock.isActive.mockReturnValue(false)
    pauseState.paused = false
    const { container } = render(<VoiceVisualiserHitStrip />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a button when audio is active', () => {
    audioPlaybackMock.isActive.mockReturnValue(true)
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('aria-label is "TTS pausieren" when not paused', () => {
    audioPlaybackMock.isActive.mockReturnValue(true)
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'TTS pausieren')
  })

  it('aria-label is "TTS fortsetzen" when paused', () => {
    audioPlaybackMock.isActive.mockReturnValue(true)
    pauseState.paused = true
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'TTS fortsetzen')
  })

  it('still renders while paused even if isActive flips false (defensive resume path)', () => {
    audioPlaybackMock.isActive.mockReturnValue(false)
    pauseState.paused = true
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('click invokes togglePause', () => {
    audioPlaybackMock.isActive.mockReturnValue(true)
    render(<VoiceVisualiserHitStrip />)
    fireEvent.click(screen.getByRole('button'))
    expect(togglePauseMock).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test --run src/features/voice/components/__tests__/VoiceVisualiserHitStrip.test.tsx
```

Expected: tests fail because the component file doesn't exist.

- [ ] **Step 3: Implement the component**

Create `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserPauseStore } from '../stores/visualiserPauseStore'

const FOCUS_OUTLINE = '2px solid rgba(140, 118, 215, 0.6)'

export function VoiceVisualiserHitStrip() {
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)
  const paused = useVisualiserPauseStore((s) => s.paused)
  const togglePause = useVisualiserPauseStore((s) => s.togglePause)

  const [isActive, setIsActive] = useState(audioPlayback.isActive())
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    setIsActive(audioPlayback.isActive())
    return audioPlayback.subscribe(() => setIsActive(audioPlayback.isActive()))
  }, [])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReducedMotion(mq.matches)
    const listener = (e: MediaQueryListEvent) => setReducedMotion(e.matches)
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  if (!enabled) return null
  if (reducedMotion) return null
  if (!isActive && !paused) return null

  return (
    <button
      type="button"
      aria-label={paused ? 'TTS fortsetzen' : 'TTS pausieren'}
      onClick={togglePause}
      style={{
        position: 'fixed',
        left: 0,
        width: '100vw',
        top: '35vh',
        height: '30vh',
        background: 'transparent',
        border: 0,
        padding: 0,
        margin: 0,
        cursor: 'pointer',
        zIndex: 2,
        touchAction: 'manipulation',
        outline: 'none',
      }}
      onFocus={(e) => { e.currentTarget.style.outline = FOCUS_OUTLINE; e.currentTarget.style.outlineOffset = '-4px' }}
      onBlur={(e) => { e.currentTarget.style.outline = 'none' }}
    />
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm test --run src/features/voice/components/__tests__/VoiceVisualiserHitStrip.test.tsx
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx \
        frontend/src/features/voice/components/__tests__/VoiceVisualiserHitStrip.test.tsx
git commit -m "Add VoiceVisualiserHitStrip overlay for tap-to-pause TTS"
```

---

## Task 9: Mount the hit-strip in `AppLayout`

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

The visualiser is already mounted near `<ToastContainer />`. Add the hit-strip as a sibling.

- [ ] **Step 1: Locate the existing `<VoiceVisualiser />` mount**

```bash
grep -n "VoiceVisualiser" /home/chris/workspace/chatsune/frontend/src/app/layouts/AppLayout.tsx
```

Note the line. The hit-strip is mounted directly below it.

- [ ] **Step 2: Add the import**

Add to the imports near the top of `frontend/src/app/layouts/AppLayout.tsx`:

```ts
import { VoiceVisualiserHitStrip } from '@/features/voice/components/VoiceVisualiserHitStrip'
```

- [ ] **Step 3: Mount the component**

Directly after the existing `<VoiceVisualiser ... />` element, add:

```tsx
<VoiceVisualiserHitStrip />
```

- [ ] **Step 4: Verify the build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm run build
```

Expected: type check clean, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "AppLayout: mount VoiceVisualiserHitStrip alongside the visualiser"
```

---

## Task 10: VoiceVisualiser pause rendering (snapshot + breathing)

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceVisualiser.tsx`

When `paused === true` from `visualiserPauseStore`: snapshot the current frequency bins on the first paused frame, then render that snapshot every frame with a slow breathing opacity multiplier (0.6 to 1.0, period 2.5s).

- [ ] **Step 1: Add the import and subscription**

Add to the imports at the top of `frontend/src/features/voice/components/VoiceVisualiser.tsx`:

```ts
import { useVisualiserPauseStore } from '../stores/visualiserPauseStore'
```

Inside the `VoiceVisualiser` function, near the existing store-reads, add:

```ts
  const paused = useVisualiserPauseStore((s) => s.paused)
```

In the existing refs block, add:

```ts
  const frozenBinsRef = useRef<Float32Array | null>(null)
```

- [ ] **Step 2: Wire `paused` into the effect dependency array**

Find the `useEffect` that owns the RAF loop (currently keyed on `[enabled, style, opacity, barCount, personaColourHex, accessors]`). Add `paused`:

```ts
  }, [enabled, style, opacity, barCount, personaColourHex, accessors, paused])
```

- [ ] **Step 3: Add the paused-render branch in the tick**

Inside the `tick` function, after computing `w`, `h`, `ctx`, and `ctx.clearRect(...)`, BEFORE the existing `playing`/`activeRef` logic, insert:

```ts
      if (paused) {
        const bins = accessors.getBins()
        if (!frozenBinsRef.current) {
          frozenBinsRef.current = bins ? bins.slice() : new Float32Array(barCount)
        }
        const t = performance.now() / 1000
        const breath = 0.8 + 0.2 * Math.sin((t * 2 * Math.PI) / 2.5)  // 0.6..1.0
        const rgb = hexToRgb(personaColourHex)
        const rgbLight = brighten(rgb)
        drawVisualiserFrame(style, ctx, w, h, frozenBinsRef.current, {
          rgb,
          rgbLight,
          opacity: opacity * breath,
          maxHeightFraction: MAX_HEIGHT_FRACTION,
        })
        rafRef.current = requestAnimationFrame(tick)
        return
      }

      // Not paused — clear any stale snapshot.
      frozenBinsRef.current = null
```

- [ ] **Step 4: Verify the build**

```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm test --run src/features/voice/
```

Expected: type check clean, all tests pass.

- [ ] **Step 5: Manual smoke check**

```bash
cd frontend && pnpm dev
```

In the browser:
- Read-aloud a multi-sentence message; while bars dance, click in the centre band → bars should freeze and breathe slowly.
- Click again → bars dance again, audio resumes from the same place.
- Read-aloud again; click to pause; click the Cockpit ⏹ → bars fade out cleanly (auto-clear path).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiser.tsx
git commit -m "VoiceVisualiser: freeze snapshot and breathe opacity when paused"
```

---

## Task 11: Manual verification pass

**Files:**
- None (verification only)

Run all manual checks from the spec, on a real device with `pnpm dev`. The list below is verbatim from `devdocs/specs/2026-04-26-voice-feedback-design.md` section 13.

- [ ] **LiveButton pulse**
  - [ ] Live mode off → LiveButton green, no pulse
  - [ ] Live mode on, mic open, silent → no (or minimal) background pulse
  - [ ] Live mode on, mic open, speak softly (just below VAD threshold) → subtle mini-pulse from the RMS path
  - [ ] Live mode on, mic open, speak clearly → strong pulse from the VAD path
  - [ ] Live mode on, mic muted → no pulse (even while speaking)
  - [ ] Live mode on, TTS playing, silent → no pulse (LiveButton steady)
  - [ ] Live mode on, TTS playing, barge in by speaking → pulse spikes the moment VAD engages

- [ ] **Pause via hit-strip — Normal mode (read-aloud)**
  - [ ] Read-aloud playing, tap centre band → bars freeze and breathe, TTS silent
  - [ ] Tap again → TTS resumes, bars dance again
  - [ ] Click a chat message above the strip → chat reacts normally (hit-strip does not block)
  - [ ] Scroll in the upper or lower third of the viewport → scrolls during TTS
  - [ ] Pause, then Cockpit ⏹ → all stops cleanly, bars disappear

- [ ] **Pause via hit-strip — Live mode**
  - [ ] Live, mic on, TTS playing, tap centre → pause + mic muted (LiveButton state reflects mute)
  - [ ] Tap again → TTS resumes, mic unmuted, pulse responds to speech again
  - [ ] Live, mic on, TTS, tap, then Cockpit ⏹ → pause clears, mic unmuted, all idle
  - [ ] Live, mic manually muted before tap, TTS, tap → pause engages, mic stays muted; tap → TTS resumes, mic stays muted (no override)
  - [ ] Live, TTS, tap, then turn LiveButton off → pause clears, Live mode off, all clean

- [ ] **Keyboard / a11y**
  - [ ] Tab to the hit-strip → subtle focus ring visible
  - [ ] Enter / Space → toggles pause exactly like a click
  - [ ] aria-label switches between "TTS pausieren" and "TTS fortsetzen"

- [ ] **Mobile**
  - [ ] Tap centre on iPhone Safari → instant pause, no double-tap zoom
  - [ ] Tap on Android Chrome → identical

- [ ] **Visualiser settings interaction**
  - [ ] Disable visualiser in user settings → no hit-strip, tap function unavailable (status quo before this feature)
  - [ ] OS `prefers-reduced-motion: reduce` enabled → no hit-strip, no LiveButton pulse
  - [ ] Persona switch mid-pause → bars recolour, keep breathing
  - [ ] Modal open during TTS (Persona Overlay, Settings) → hit-strip sits behind modal (z-index correct); modal click does not bleed through to pause

- [ ] **No regression**
  - [ ] Cockpit ⏹ continues to fully stop TTS in all modes
  - [ ] Existing visualiser behaviour (dance + fade) unchanged when pause feature is not used
  - [ ] Audio quality identical with and without pause feature engaged

If any check fails, file the issue inline (open the relevant file, fix, re-verify, commit). After all checks pass, no further commit is needed — the feature is done.

---

## Notes for the implementer

- **Execute tasks in numerical order (1 → 11).** The order respects all dependencies; deviating from it requires re-checking the dependency graph.
- **Each task ends with one commit.** Do not bundle multiple tasks into one commit.
- **Do not merge, do not push, do not switch branches.** Stay on the current branch until the user explicitly says to integrate.
- **Build before manual verify.** Always run `pnpm tsc --noEmit` (or the relevant test bundle) before opening the browser. CI uses `pnpm run build` — `tsc --noEmit` catches almost everything but `pnpm run build` is the final word.
- **No backend, no DTO, no migration.** This plan is 100 % frontend.
