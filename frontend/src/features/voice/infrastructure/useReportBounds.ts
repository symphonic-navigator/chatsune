import { useCallback, useEffect, useRef } from 'react'
import {
  useVisualiserLayoutStore,
  type LayoutTarget,
} from '../stores/visualiserLayoutStore'

/**
 * Reports the viewport-relative x and width of a DOM element into the
 * layout store under `target`. Returns a callback ref that the consumer
 * attaches to the element it wants measured:
 *
 *   const setRef = useReportBounds<HTMLDivElement>('chatview')
 *   <div ref={setRef}>...</div>
 *
 * A callback ref is used (rather than a `RefObject` argument) so the
 * hook reacts to React attaching/detaching the underlying DOM node. With
 * a `RefObject` and a `useEffect` keyed on stable deps the effect would
 * fire once at mount, observe `ref.current === null` (the element is
 * conditionally rendered), and never re-run when the element later
 * appears — leaving the slot stuck at `null` until a hard reload.
 *
 * Re-measures on every event that could shift the element's bounds:
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
 * Clears the slot to `null` when the node detaches and on hook unmount.
 *
 * Uses `getBoundingClientRect()` rather than `entry.contentRect` because
 * we want viewport-relative coordinates (the visualiser canvas is a
 * fixed overlay sized to the viewport), and `contentRect` is
 * element-relative.
 */
export function useReportBounds<T extends HTMLElement = HTMLElement>(
  target: LayoutTarget,
): (node: T | null) => void {
  // Holds the teardown for the currently-attached node's observers and
  // listeners, so we can dispose of them before installing new ones when
  // the callback ref fires with a different node (or `null`).
  const cleanupRef = useRef<(() => void) | null>(null)

  const setRef = useCallback(
    (node: T | null) => {
      // Tear down anything wired up to the previous node first.
      if (cleanupRef.current) {
        cleanupRef.current()
        cleanupRef.current = null
      }

      if (!node) {
        // Detach: clear the slot. (Unmount is handled by the effect
        // below so the store also clears if the consumer unmounts
        // without first detaching the ref.)
        useVisualiserLayoutStore.getState().setBounds(target, null)
        return
      }

      const report = () => {
        const r = node.getBoundingClientRect()
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
      ro.observe(node)
      window.addEventListener('resize', report)
      const unsubStore = useVisualiserLayoutStore.subscribe((state, prev) => {
        for (const key of ['chatview', 'textColumn'] as const) {
          if (key !== target && state[key] !== prev[key]) {
            report()
            return
          }
        }
      })

      cleanupRef.current = () => {
        ro.disconnect()
        window.removeEventListener('resize', report)
        unsubStore()
      }
    },
    [target],
  )

  // On hook unmount tear down whatever is still attached and clear the
  // slot. This covers the case where the consumer unmounts while the
  // node is still mounted (React will call the callback ref with `null`
  // for refs on the same element being unmounted, but doing this here
  // makes the contract explicit and resilient to any timing edge cases).
  useEffect(() => {
    return () => {
      if (cleanupRef.current) {
        cleanupRef.current()
        cleanupRef.current = null
      }
      useVisualiserLayoutStore.getState().setBounds(target, null)
    }
  }, [target])

  return setRef
}
