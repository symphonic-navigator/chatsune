import { PointerSensor, useSensor, useSensors } from "@dnd-kit/core"

/**
 * Shared DnD-Kit sensor configuration for Chatsune.
 *
 * A `PointerSensor` with a 250 ms activation delay plus 5 px tolerance means
 * that on touch devices a drag only starts after a deliberate long-press —
 * short taps and vertical scroll gestures are not hijacked by DnD. On desktop
 * the delay is essentially invisible for mouse users because click-and-drag
 * still works once the pointer has moved past the tolerance.
 */
export function useDndSensors() {
  return useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { delay: 250, tolerance: 5 },
    }),
  )
}
