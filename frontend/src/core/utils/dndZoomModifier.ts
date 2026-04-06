import type { Modifier } from "@dnd-kit/core"
import { useDisplaySettings } from "../store/displaySettingsStore"

/**
 * Compensates for CSS `zoom` on the body element.
 *
 * When `body { zoom: X }` is active, @dnd-kit's pointer coordinates
 * and getBoundingClientRect() values are in different coordinate spaces.
 * This modifier scales the transform to match the zoomed space.
 */
export const zoomModifier: Modifier = ({ transform, activeNodeRect }) => {
  const zoom = useDisplaySettings.getState().settings.uiScale / 100
  if (zoom === 1) return transform
  const offsetFactor = 1 / zoom - 1
  return {
    ...transform,
    x: transform.x / zoom + (activeNodeRect?.left ?? 0) * offsetFactor,
    y: transform.y / zoom + (activeNodeRect?.top ?? 0) * offsetFactor,
  }
}

export const zoomModifiers = [zoomModifier]
