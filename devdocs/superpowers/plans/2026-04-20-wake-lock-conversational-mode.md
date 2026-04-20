# Wake Lock in Conversational Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the mobile screen awake while Conversational Mode is active, so the WebSocket survives and hands-free voice chat stays live.

**Architecture:** Introduce a generic `useWakeLock(shouldHold: boolean)` hook in `frontend/src/core/hooks/` that wraps `navigator.wakeLock.request('screen')`, handles `visibilitychange`-based re-acquisition, and no-ops on unsupported browsers. `ChatView.tsx` composes it next to the existing `useConversationMode` call, feeding `useConversationModeStore(s => s.active)` as the `shouldHold` argument.

**Tech Stack:** React 19, TypeScript, Vitest 4, `@testing-library/react` 16, Zustand.

**Spec:** `devdocs/superpowers/specs/2026-04-20-wake-lock-conversational-mode-design.md`

---

## File Structure

- **Create:** `frontend/src/core/hooks/useWakeLock.ts` — the hook, ~60 LOC, no external deps other than `react`.
- **Create:** `frontend/src/core/hooks/useWakeLock.test.tsx` — Vitest suite covering acquire/release/visibility/unsupported/unmount.
- **Modify:** `frontend/src/features/chat/ChatView.tsx` — two new imports + two lines near the existing `useConversationMode` call at line 981.

No other files change.

---

## Task 1: Scaffold the hook and write the full failing test suite

**Files:**
- Create: `frontend/src/core/hooks/useWakeLock.ts`
- Create: `frontend/src/core/hooks/useWakeLock.test.tsx`

Writing the whole test suite up front (and a stub implementation so imports resolve) is more efficient than one-test-per-cycle for a hook this small.

- [ ] **Step 1: Create an empty stub hook so imports resolve**

Create `frontend/src/core/hooks/useWakeLock.ts` with the following exact contents:

```ts
export function useWakeLock(_shouldHold: boolean): void {
  // intentionally empty — filled in by Task 2
}
```

- [ ] **Step 2: Write the failing test suite**

Create `frontend/src/core/hooks/useWakeLock.test.tsx` with the following exact contents:

```tsx
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWakeLock } from './useWakeLock'

// A minimal fake WakeLockSentinel. `released` is flipped to true when
// `release()` is called, mirroring the real browser behaviour so the hook's
// "is the sentinel still held?" check works in tests.
type FakeSentinel = {
  released: boolean
  release: ReturnType<typeof vi.fn>
}

function createFakeSentinel(): FakeSentinel {
  const sentinel: FakeSentinel = {
    released: false,
    release: vi.fn(async () => {
      sentinel.released = true
    }),
  }
  return sentinel
}

// Track the sentinels the mock hands out so tests can inspect / mutate them.
let sentinels: FakeSentinel[] = []
let mockRequest: ReturnType<typeof vi.fn>

function installWakeLock(): void {
  mockRequest = vi.fn(async (_type: 'screen') => {
    const s = createFakeSentinel()
    sentinels.push(s)
    return s
  })
  Object.defineProperty(navigator, 'wakeLock', {
    configurable: true,
    value: { request: mockRequest },
  })
}

function uninstallWakeLock(): void {
  // `delete` requires the property to be configurable, which we set above.
  delete (navigator as unknown as { wakeLock?: unknown }).wakeLock
}

function setVisibility(state: 'visible' | 'hidden'): void {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value: state,
  })
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  sentinels = []
  setVisibility('visible')
  installWakeLock()
})

afterEach(() => {
  uninstallWakeLock()
  vi.restoreAllMocks()
})

describe('useWakeLock', () => {
  it('does not request the lock when shouldHold is false', () => {
    renderHook(() => useWakeLock(false))
    expect(mockRequest).not.toHaveBeenCalled()
  })

  it('requests the lock exactly once when shouldHold transitions false → true', async () => {
    const { rerender } = renderHook(({ hold }) => useWakeLock(hold), {
      initialProps: { hold: false },
    })
    expect(mockRequest).not.toHaveBeenCalled()

    await act(async () => {
      rerender({ hold: true })
    })

    expect(mockRequest).toHaveBeenCalledTimes(1)
    expect(mockRequest).toHaveBeenCalledWith('screen')
  })

  it('releases the sentinel when shouldHold transitions true → false', async () => {
    const { rerender } = renderHook(({ hold }) => useWakeLock(hold), {
      initialProps: { hold: true },
    })
    await act(async () => {}) // let the async acquire resolve

    expect(sentinels).toHaveLength(1)
    const first = sentinels[0]
    expect(first.released).toBe(false)

    await act(async () => {
      rerender({ hold: false })
    })

    expect(first.release).toHaveBeenCalledTimes(1)
    expect(first.released).toBe(true)
  })

  it('re-acquires on visibilitychange → visible when the sentinel was auto-released', async () => {
    renderHook(() => useWakeLock(true))
    await act(async () => {})

    expect(sentinels).toHaveLength(1)
    const first = sentinels[0]

    // Simulate the browser auto-releasing the lock when the tab was hidden.
    first.released = true
    setVisibility('hidden')

    // Now the user returns.
    await act(async () => {
      setVisibility('visible')
    })

    // A second request should have been made, handing out a fresh sentinel.
    expect(mockRequest).toHaveBeenCalledTimes(2)
    expect(sentinels).toHaveLength(2)
    expect(sentinels[1].released).toBe(false)
  })

  it('does nothing and throws nothing when navigator.wakeLock is unavailable', () => {
    uninstallWakeLock()
    expect(() => {
      renderHook(() => useWakeLock(true))
    }).not.toThrow()
  })

  it('releases the sentinel on unmount', async () => {
    const { unmount } = renderHook(() => useWakeLock(true))
    await act(async () => {})

    expect(sentinels).toHaveLength(1)
    const first = sentinels[0]

    await act(async () => {
      unmount()
    })

    expect(first.release).toHaveBeenCalledTimes(1)
    expect(first.released).toBe(true)
  })
})
```

- [ ] **Step 3: Run the suite and confirm it fails**

Run: `cd frontend && pnpm exec vitest run src/core/hooks/useWakeLock.test.tsx`

Expected: multiple failing tests. The stub hook does nothing, so assertions like "requests the lock" fail. The unsupported-browser test may happen to pass (the stub throws nothing).

- [ ] **Step 4: Commit the failing suite**

```bash
git -C /home/chris/workspace/chatsune add frontend/src/core/hooks/useWakeLock.ts frontend/src/core/hooks/useWakeLock.test.tsx
git -C /home/chris/workspace/chatsune commit -m "$(cat <<'EOF'
Add failing useWakeLock test suite and stub

Stub hook plus the complete Vitest suite. Implementation follows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Implement the hook

**Files:**
- Modify: `frontend/src/core/hooks/useWakeLock.ts`

- [ ] **Step 1: Replace the stub with the real implementation**

Overwrite `frontend/src/core/hooks/useWakeLock.ts` with the following exact contents:

```ts
import { useEffect } from 'react'

/**
 * Keep the device screen awake while `shouldHold` is `true`.
 *
 * Wraps the Screen Wake Lock API. Handles the browser's automatic release
 * when the tab becomes hidden by re-requesting on `visibilitychange` →
 * `visible`. On browsers without `navigator.wakeLock`, the hook is a silent
 * no-op; Conversational Mode still runs, the OS screen timeout just behaves
 * as usual.
 */
export function useWakeLock(shouldHold: boolean): void {
  useEffect(() => {
    if (!shouldHold) return
    if (!('wakeLock' in navigator)) return

    let sentinel: WakeLockSentinel | null = null
    let cancelled = false

    const acquire = async (): Promise<void> => {
      if (sentinel && !sentinel.released) return
      try {
        const fresh = await navigator.wakeLock.request('screen')
        if (cancelled) {
          await fresh.release()
          return
        }
        sentinel = fresh
      } catch (err) {
        // NotAllowedError fires if the document is not fully active (e.g.
        // acquire attempted while the page is transitioning). Not
        // user-actionable; debug-log and move on.
        console.debug('[useWakeLock] request failed:', err)
      }
    }

    const handleVisibilityChange = (): void => {
      if (document.visibilityState === 'visible') {
        void acquire()
      }
    }

    void acquire()
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      if (sentinel && !sentinel.released) {
        void sentinel.release()
      }
      sentinel = null
    }
  }, [shouldHold])
}
```

- [ ] **Step 2: Run the suite and confirm it passes**

Run: `cd frontend && pnpm exec vitest run src/core/hooks/useWakeLock.test.tsx`

Expected: all six tests pass.

- [ ] **Step 3: If TypeScript complains about `WakeLockSentinel` or `navigator.wakeLock`**

TypeScript's DOM lib has included these types since TS 4.8. If the build fails with "Cannot find name 'WakeLockSentinel'" or similar:

Run: `cd frontend && pnpm exec tsc --noEmit` to reproduce the error. Then check `frontend/tsconfig.json` for the `lib` setting. If `"DOM"` is present but the types are still missing, add explicit ambient declarations at the top of `useWakeLock.ts`:

```ts
/// <reference lib="dom" />
```

This should not be needed in practice — noted here as a contingency only.

- [ ] **Step 4: Type-check the whole frontend**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: no errors.

- [ ] **Step 5: Commit the implementation**

```bash
git -C /home/chris/workspace/chatsune add frontend/src/core/hooks/useWakeLock.ts
git -C /home/chris/workspace/chatsune commit -m "$(cat <<'EOF'
Implement useWakeLock hook

Wraps navigator.wakeLock with visibilitychange-driven re-acquisition and
silent no-op fallback on browsers that lack the API.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Integrate into ChatView.tsx

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

The integration is two new imports and two lines in the component body.

- [ ] **Step 1: Add the imports**

At the top of `frontend/src/features/chat/ChatView.tsx`, alongside the existing imports, add:

```tsx
import { useWakeLock } from '../../core/hooks/useWakeLock'
import { useConversationModeStore } from '../voice/stores/conversationModeStore'
```

If `useConversationModeStore` is already imported in `ChatView.tsx` (possible, since the file interacts with conversation mode extensively), skip its import. Check with:

Run: `grep -n useConversationModeStore /home/chris/workspace/chatsune/frontend/src/features/chat/ChatView.tsx`

If already present: add only the `useWakeLock` import.

- [ ] **Step 2: Call the hook adjacent to useConversationMode**

Locate the existing call at `ChatView.tsx:981` (line number may drift — search for `useConversationMode({`). Immediately before or after it, add:

```tsx
const conversationActive = useConversationModeStore(s => s.active)
useWakeLock(conversationActive)
```

If `conversationActive` is already derived in the component for another purpose (check with `grep -n "s\.active" /home/chris/workspace/chatsune/frontend/src/features/chat/ChatView.tsx`), reuse that binding instead of introducing a second selector call.

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: no errors.

- [ ] **Step 4: Full production build**

Run: `cd frontend && pnpm run build`

Expected: build succeeds, no TypeScript errors, no lint errors from the changes. If the build surfaces unrelated errors pre-existing on the branch, stop and report.

- [ ] **Step 5: Run the full Vitest suite once**

Run: `cd frontend && pnpm exec vitest run`

Expected: all tests pass, including the six new `useWakeLock` tests and the pre-existing `useConversationMode` suites (no regressions).

- [ ] **Step 6: Commit the integration**

```bash
git -C /home/chris/workspace/chatsune add frontend/src/features/chat/ChatView.tsx
git -C /home/chris/workspace/chatsune commit -m "$(cat <<'EOF'
Hold screen wake lock while Conversational Mode is active

Conversational Mode is hands-free by design; on mobile the OS would
otherwise sleep the screen, suspend the tab, and drop the WebSocket.
The wake lock keeps the display lit for as long as the user is in the
mode and is released the moment they leave.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Merge to master

**Context:** CLAUDE.md (`/home/chris/workspace/chatsune/CLAUDE.md`) states: "Please always merge to master after implementation". If this plan is being executed on a feature branch, merge now. If it was executed directly on `master` (which is the case for the current working tree), this task is a no-op beyond a final sanity check.

- [ ] **Step 1: Check the current branch**

Run: `git -C /home/chris/workspace/chatsune rev-parse --abbrev-ref HEAD`

If it is `master`: skip to Step 3.

If it is a feature branch:

- [ ] **Step 2: Merge to master**

```bash
git -C /home/chris/workspace/chatsune checkout master
git -C /home/chris/workspace/chatsune merge --no-ff <feature-branch-name>
```

- [ ] **Step 3: Confirm `git status` is clean**

Run: `git -C /home/chris/workspace/chatsune status`

Expected: "nothing to commit, working tree clean".

---

## Task 5: Manual verification on a real mobile device

**Files:** none — this is a physical test.

This task is **required** before declaring the feature done. Unit tests cannot verify that the OS actually honours the wake lock.

Pre-requisites: the changes are deployed to the mobile PWA (the user typically runs the dev build or a short-turnaround Hetzner deploy — follow whatever flow was last used for mobile testing).

- [ ] **Step 1: Set the device screen timeout to ~30 s**

On Android: Settings → Display → Screen timeout → 30 seconds (or the shortest realistic option).

- [ ] **Step 2: Baseline — confirm the bug still exists without entering Conversational Mode**

1. Open the Chatsune PWA.
2. Start a normal chat (do NOT enter Conversational Mode).
3. Put the phone face-up, do not touch it.
4. Expected: the screen dims and sleeps after the 30 s timeout.

- [ ] **Step 3: Enter Conversational Mode and verify the screen stays awake**

1. In the same PWA session, enter Conversational Mode.
2. Put the phone face-up, do not touch it.
3. Wait ≥ 60 s.
4. Expected: the screen remains fully lit throughout. The VAD listening indicator stays visible and responsive.

- [ ] **Step 4: Exit Conversational Mode and verify the screen dims again**

1. Exit Conversational Mode.
2. Put the phone face-up, do not touch it.
3. Expected: the screen dims and sleeps after the 30 s timeout, just like Step 2.

- [ ] **Step 5: App-switch recovery**

1. Enter Conversational Mode.
2. Switch to a different app (e.g. home screen) and wait ≥ 20 s.
3. Switch back to the Chatsune PWA.
4. Put the phone face-up, wait ≥ 60 s.
5. Expected: the screen stays lit again. (The wake lock is auto-released by the browser during the hidden period and re-acquired on `visibilitychange` → `visible`.)

- [ ] **Step 6: Report results**

If every step behaves as expected, the feature is complete. If any step fails, stop and report the specific behaviour observed for debugging before claiming completion.

---

## Post-implementation notes

- No memory to update. The UX rule "continuous voice = long-session mode, ambient features branch from it" has already been written to long-term memory.
- No ADR or docs change is needed; the spec and this plan together document the decision.
