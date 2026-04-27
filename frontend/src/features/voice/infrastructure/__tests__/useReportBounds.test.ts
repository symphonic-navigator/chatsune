import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRef } from 'react'
import { useReportBounds } from '../useReportBounds'
import { useVisualiserLayoutStore } from '../../stores/visualiserLayoutStore'

type ROCallback = (entries: ResizeObserverEntry[]) => void

let observers: { cb: ROCallback; el: Element | null }[] = []
const OriginalRO = globalThis.ResizeObserver
const originalGBCR = Element.prototype.getBoundingClientRect

function mockRect(x: number, w: number) {
  Element.prototype.getBoundingClientRect = vi.fn(() => ({
    x, y: 0, width: w, height: 100,
    top: 0, left: x, right: x + w, bottom: 100,
    toJSON: () => ({}),
  }))
}

function fireAll() {
  for (const obs of observers) {
    if (!obs.el) continue
    obs.cb([{ target: obs.el } as ResizeObserverEntry])
  }
}

beforeEach(() => {
  observers = []
  globalThis.ResizeObserver = class {
    private cb: ROCallback
    constructor(cb: ROCallback) {
      this.cb = cb
      observers.push({ cb, el: null })
    }
    observe(el: Element) {
      const slot = observers.find((o) => o.cb === this.cb)
      if (slot) slot.el = el
    }
    unobserve() {}
    disconnect() {
      const slot = observers.find((o) => o.cb === this.cb)
      if (slot) slot.el = null
    }
  } as unknown as typeof ResizeObserver
  useVisualiserLayoutStore.setState({ chatview: null, textColumn: null })
})

afterEach(() => {
  globalThis.ResizeObserver = OriginalRO
  Element.prototype.getBoundingClientRect = originalGBCR
})

describe('useReportBounds', () => {
  it('reports bounds for the chatview target on mount', () => {
    mockRect(240, 1680)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      // Simulate a real DOM element being attached.
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'chatview')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 240, w: 1680 })
  })

  it('reports bounds for the textColumn target', () => {
    mockRect(816, 768)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'textColumn')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 816, w: 768 })
  })

  it('updates bounds when the observer fires', () => {
    mockRect(100, 1000)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'chatview')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 100, w: 1000 })
    mockRect(150, 1100)
    fireAll()
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 150, w: 1100 })
  })

  it('re-measures on window resize', () => {
    mockRect(100, 1000)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'chatview')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 100, w: 1000 })
    mockRect(120, 900)
    window.dispatchEvent(new Event('resize'))
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 120, w: 900 })
  })

  it('re-measures when another slot updates (cross-slot trigger)', () => {
    // Simulates the sidebar-collapse / window-resize case where the
    // chatview's bounds change but the textColumn's max-w-3xl width
    // stays constant — only its x shifts. RO would not fire on the
    // textColumn; the cross-slot subscription must.
    mockRect(116, 768)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'textColumn')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 116, w: 768 })
    mockRect(50, 768)
    useVisualiserLayoutStore.getState().setBounds('chatview', { x: 0, w: 900 })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 50, w: 768 })
  })

  it('skips no-op writes to avoid cross-slot subscription loops', () => {
    mockRect(100, 1000)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'chatview')
      return ref
    })
    const before = useVisualiserLayoutStore.getState().chatview
    // Trigger a re-measure but keep the rect identical: setBounds must
    // not be called, so the reference stays stable.
    window.dispatchEvent(new Event('resize'))
    const after = useVisualiserLayoutStore.getState().chatview
    expect(after).toBe(before)
  })

  it('clears the slot to null on unmount', () => {
    mockRect(0, 800)
    const { unmount } = renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'textColumn')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 0, w: 800 })
    unmount()
    expect(useVisualiserLayoutStore.getState().textColumn).toBeNull()
  })
})
