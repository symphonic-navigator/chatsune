import { create } from 'zustand'

export interface Bounds {
  /** Viewport-relative left edge in CSS pixels. */
  x: number
  /** Width in CSS pixels. */
  w: number
}

export type LayoutTarget = 'chatview' | 'textColumn'

interface LayoutState {
  chatview: Bounds | null
  textColumn: Bounds | null
  setBounds: (target: LayoutTarget, bounds: Bounds | null) => void
}

export const useVisualiserLayoutStore = create<LayoutState>((set) => ({
  chatview: null,
  textColumn: null,
  setBounds: (target, bounds) => set({ [target]: bounds } as Pick<LayoutState, LayoutTarget>),
}))
