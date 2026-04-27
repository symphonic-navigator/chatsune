import { useEffect, type RefObject } from 'react'
import {
  useVisualiserLayoutStore,
  type LayoutTarget,
} from '../stores/visualiserLayoutStore'

/**
 * Reports the viewport-relative x and width of `ref.current` into the
 * layout store under `target`, both on mount and on every ResizeObserver
 * notification. Clears the slot to `null` on unmount.
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
    const setBounds = useVisualiserLayoutStore.getState().setBounds
    const report = () => {
      const r = el.getBoundingClientRect()
      setBounds(target, { x: r.x, w: r.width })
    }
    report()
    const ro = new ResizeObserver(report)
    ro.observe(el)
    return () => {
      ro.disconnect()
      setBounds(target, null)
    }
  }, [ref, target])
}
