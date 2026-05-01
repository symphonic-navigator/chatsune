import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, render, act } from '@testing-library/react'
import { createElement, useState } from 'react'
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
    render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('chatview')
        return createElement('div', { ref: setRef })
      }),
    )
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 240, w: 1680 })
  })

  it('reports bounds for the textColumn target', () => {
    mockRect(816, 768)
    render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('textColumn')
        return createElement('div', { ref: setRef })
      }),
    )
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 816, w: 768 })
  })

  it('updates bounds when the observer fires', () => {
    mockRect(100, 1000)
    render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('chatview')
        return createElement('div', { ref: setRef })
      }),
    )
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 100, w: 1000 })
    mockRect(150, 1100)
    act(() => {
      fireAll()
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 150, w: 1100 })
  })

  it('re-measures on window resize', () => {
    mockRect(100, 1000)
    render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('chatview')
        return createElement('div', { ref: setRef })
      }),
    )
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 100, w: 1000 })
    mockRect(120, 900)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 120, w: 900 })
  })

  it('re-measures when another slot updates (cross-slot trigger)', () => {
    // Simulates the sidebar-collapse / window-resize case where the
    // chatview's bounds change but the textColumn's max-w-3xl width
    // stays constant — only its x shifts. RO would not fire on the
    // textColumn; the cross-slot subscription must.
    mockRect(116, 768)
    render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('textColumn')
        return createElement('div', { ref: setRef })
      }),
    )
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 116, w: 768 })
    mockRect(50, 768)
    act(() => {
      useVisualiserLayoutStore.getState().setBounds('chatview', { x: 0, w: 900 })
    })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 50, w: 768 })
  })

  it('skips no-op writes to avoid cross-slot subscription loops', () => {
    mockRect(100, 1000)
    render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('chatview')
        return createElement('div', { ref: setRef })
      }),
    )
    const before = useVisualiserLayoutStore.getState().chatview
    // Trigger a re-measure but keep the rect identical: setBounds must
    // not be called, so the reference stays stable.
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    const after = useVisualiserLayoutStore.getState().chatview
    expect(after).toBe(before)
  })

  it('clears the slot to null on unmount', () => {
    mockRect(0, 800)
    const { unmount } = render(
      createElement(function Cmp() {
        const setRef = useReportBounds<HTMLDivElement>('textColumn')
        return createElement('div', { ref: setRef })
      }),
    )
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 0, w: 800 })
    unmount()
    expect(useVisualiserLayoutStore.getState().textColumn).toBeNull()
  })

  it('reports bounds when the ref is attached after the initial render (mount-order race)', () => {
    // Reproduces the bug where a parent renders the target conditionally:
    // on first render the element is absent, so a useEffect-with-stable-deps
    // hook misses the later attach. The callback-ref API must catch the
    // attach when the node finally mounts.
    mockRect(240, 1680)
    let setShow: (v: boolean) => void = () => {}
    render(
      createElement(function Cmp() {
        const [show, _setShow] = useState(false)
        setShow = _setShow
        const setRef = useReportBounds<HTMLDivElement>('chatview')
        return show ? createElement('div', { ref: setRef }) : null
      }),
    )
    // Element absent → slot stays null.
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
    // Flip state → element mounts → callback ref fires → bounds reported.
    act(() => {
      setShow(true)
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 240, w: 1680 })
  })

  it('tears down old observers and reports new node bounds when the ref is called with a different node', () => {
    // Uses renderHook so we can drive the callback ref imperatively with
    // two distinct DOM nodes and verify the previous observer is gone.
    mockRect(10, 100)
    const { result } = renderHook(() => useReportBounds<HTMLDivElement>('chatview'))
    const setRef = result.current

    const nodeA = document.createElement('div')
    act(() => {
      setRef(nodeA)
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 10, w: 100 })
    expect(observers.filter((o) => o.el !== null).length).toBe(1)

    // Replace with a fresh node — old observer must disconnect, new one
    // must observe the new node and report its bounds.
    mockRect(500, 200)
    const nodeB = document.createElement('div')
    act(() => {
      setRef(nodeB)
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 500, w: 200 })
    // Exactly one live observer remains; the previous one was disconnected.
    expect(observers.filter((o) => o.el !== null).length).toBe(1)
  })
})
