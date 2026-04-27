import { useEffect, type RefObject } from 'react'
import {
  useVisualiserLayoutStore,
  type LayoutTarget,
} from '../stores/visualiserLayoutStore'

/**
 * Reports the viewport-relative x and width of `ref.current` into the
 * layout store under `target`. Re-measures on every event that could
 * shift the element's bounds:
 *
 *   - ResizeObserver — element's own size change.
 *   - window.resize — viewport change. RO would not fire on an
 *     `mx-auto` child whose width is capped (e.g. `max-w-3xl`) when the
 *     parent shrinks but stays wider than the cap: the child re-centres
 *     so its `x` shifts but its `w` does not.
 *   - Other-slot updates — ancestor layout shift (e.g. sidebar collapse)
 *     can move the element without resizing it. RO on the element would
 *     not fire; re-measure when any sibling slot reports a change.
 *
 * Clears the slot to `null` on unmount.
 *
 * Uses `getBoundingClientRect()` rather than `entry.contentRect` because
 * we want viewport-relative coordinates (the visualiser canvas is a
 * fixed overlay sized to the viewport), and `contentRect` is
 * element-relative.
 */
export function useReportBounds(
  ref: RefObject<HTMLElement | null>,
  target: LayoutTarget,
): void {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const report = () => {
      const r = el.getBoundingClientRect()
      const next = { x: r.x, w: r.width }
      const state = useVisualiserLayoutStore.getState()
      const current = state[target]
      // Skip no-op writes so the cross-slot subscription below cannot
      // loop on its own updates.
      if (current && current.x === next.x && current.w === next.w) return
      state.setBounds(target, next)
    }
    report()
    const ro = new ResizeObserver(report)
    ro.observe(el)
    window.addEventListener('resize', report)
    const unsubStore = useVisualiserLayoutStore.subscribe((state, prev) => {
      for (const key of ['chatview', 'textColumn'] as const) {
        if (key !== target && state[key] !== prev[key]) {
          report()
          return
        }
      }
    })
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', report)
      unsubStore()
      useVisualiserLayoutStore.getState().setBounds(target, null)
    }
  }, [ref, target])
}
