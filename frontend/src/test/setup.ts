import { afterEach, beforeEach, vi } from "vitest"
import { cleanup } from "@testing-library/react"

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

beforeEach(() => {
  localStorage.clear()
  // Clear module cache to reset module-level state between tests
  vi.resetModules()
})

afterEach(() => {
  cleanup()
})
