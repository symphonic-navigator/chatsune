import { create } from 'zustand'

/**
 * Tracks the stack of currently open overlays for the back-button close
 * mechanism. Each entry pairs an overlay id with the close handler the
 * popstate listener should invoke when that entry leaves the browser
 * history.
 *
 * The store is the authoritative truth — browser history entries pushed
 * by `useBackButtonClose` are markers only. On logout or other reset
 * paths, callers should `clear()` to avoid stale entries firing onClose
 * against unmounted components.
 */
export interface OverlayEntry {
  overlayId: string
  onClose: () => void
}

interface HistoryStackState {
  stack: OverlayEntry[]
  push: (overlayId: string, onClose: () => void) => void
  popTop: () => OverlayEntry | null
  peek: () => OverlayEntry | null
  clear: () => void
  remove: (overlayId: string) => { removed: boolean; wasTop: boolean }
}

export const useHistoryStackStore = create<HistoryStackState>((set, get) => ({
  stack: [],
  push: (overlayId, onClose) =>
    set((state) => {
      // If the same id is already present, replace its entry rather than
      // duplicating. Hook contract guarantees only one push per
      // open-transition, but defensive replace keeps the stack honest if
      // a component re-mounts under odd timings.
      const filtered = state.stack.filter((e) => e.overlayId !== overlayId)
      return { stack: [...filtered, { overlayId, onClose }] }
    }),
  popTop: () => {
    const { stack } = get()
    if (stack.length === 0) return null
    const top = stack[stack.length - 1]
    set({ stack: stack.slice(0, -1) })
    return top
  },
  peek: () => {
    const { stack } = get()
    return stack.length === 0 ? null : stack[stack.length - 1]
  },
  clear: () => set({ stack: [] }),
  remove: (overlayId) => {
    const { stack } = get()
    const idx = stack.findIndex((e) => e.overlayId === overlayId)
    if (idx === -1) return { removed: false, wasTop: false }
    const wasTop = idx === stack.length - 1
    set({ stack: stack.slice(0, idx).concat(stack.slice(idx + 1)) })
    return { removed: true, wasTop }
  },
}))
