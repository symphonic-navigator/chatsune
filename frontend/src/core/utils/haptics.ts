import { useHapticsStore } from '../store/hapticsStore'

// Thin wrappers around the Vibration API. All helpers are no-ops when the API
// is missing (iOS Safari, desktop browsers) or when the user has opted out via
// the haptics store. Patterns are deliberately short and subtle — we want
// tactile acknowledgement, not a noisy buzz.

function vibrate(pattern: number | number[]): void {
  if (typeof navigator === 'undefined') return
  if (!useHapticsStore.getState().enabled) return
  const nav = navigator as Navigator & { vibrate?: (p: number | number[]) => boolean }
  nav.vibrate?.(pattern)
}

/** Single short tap — e.g. sending a message. */
export function hapticTap(): void {
  vibrate(10)
}

/** Double pulse for successful operations. */
export function hapticSuccess(): void {
  vibrate([10, 30, 10])
}

/** Stronger pattern for errors and destructive rejections. */
export function hapticError(): void {
  vibrate([40, 30, 40])
}

/** Slightly longer buzz to acknowledge a long-press / drag start. */
export function hapticLongPress(): void {
  vibrate(20)
}
