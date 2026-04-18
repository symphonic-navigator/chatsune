import { afterEach, beforeEach, vi } from "vitest"
import { cleanup } from "@testing-library/react"
import "@testing-library/jest-dom"

// Mock localStorage for jsdom environment
const localStorageMock = (() => {
  let store: Record<string, string> = {}

  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString()
    },
    removeItem: (key: string) => {
      delete store[key]
    },
    clear: () => {
      store = {}
    },
  }
})()

Object.defineProperty(window, "localStorage", {
  value: localStorageMock,
})

// ResizeObserver is not implemented in jsdom
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// AudioWorkletNode is not implemented in jsdom. SoundTouchNode from
// @soundtouchjs/audio-worklet extends it at module-load time, so any test that
// transitively imports audioPlayback hits a ReferenceError without this stub.
// Tests that exercise playback mock the loader directly; this stub just lets
// the module graph resolve.
if (typeof globalThis.AudioWorkletNode === "undefined") {
  // @ts-expect-error — minimal stub for jsdom
  globalThis.AudioWorkletNode = class AudioWorkletNode {}
}

beforeEach(() => {
  localStorage.clear()
  // Clear module cache to reset module-level state between tests
  vi.resetModules()
})

afterEach(() => {
  cleanup()
})
