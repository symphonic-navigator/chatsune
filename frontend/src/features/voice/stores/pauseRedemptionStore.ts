import { create } from 'zustand'

interface PauseRedemptionState {
  /** True while the redemption window is open (silence detected, pie visible). */
  active: boolean
  /** performance.now() value when redemption started, or null. */
  startedAt: number | null
  /**
   * Redemption window currently in force (snapshot taken at `start()`-time
   * so a user sliding the setting mid-pause does not mutate the live pie).
   */
  windowMs: number
  /** Open the window. Called by audioCapture once the grace period has elapsed. */
  start(windowMs: number): void
  /** Close the window. Idempotent — safe to call from multiple cleanup edges. */
  clear(): void
}

export const usePauseRedemptionStore = create<PauseRedemptionState>((set) => ({
  active: false,
  startedAt: null,
  windowMs: 0,
  start: (windowMs) => set({ active: true, startedAt: performance.now(), windowMs }),
  clear: () => set({ active: false, startedAt: null, windowMs: 0 }),
}))
