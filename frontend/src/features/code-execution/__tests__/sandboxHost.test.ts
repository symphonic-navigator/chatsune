import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Fake Worker class that lets the test drive message/error/hang paths.
type Listener = (...args: unknown[]) => void
let currentWorker: FakeWorker | null = null

class FakeWorker {
  listeners: Record<string, Listener[]> = {}
  terminated = false
  postedMessages: unknown[] = []

  constructor(_url: unknown, _opts?: unknown) {
    currentWorker = this
  }

  addEventListener(type: string, cb: Listener): void {
    this.listeners[type] = this.listeners[type] || []
    this.listeners[type].push(cb)
  }

  postMessage(msg: unknown): void {
    this.postedMessages.push(msg)
  }

  terminate(): void {
    this.terminated = true
  }

  // Test helpers
  emitMessage(data: unknown): void {
    ;(this.listeners['message'] || []).forEach((cb) =>
      cb({ data } as unknown),
    )
  }

  emitError(message: string): void {
    ;(this.listeners['error'] || []).forEach((cb) =>
      cb({ message } as unknown),
    )
  }
}

beforeEach(() => {
  currentWorker = null
  vi.stubGlobal('Worker', FakeWorker)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Import AFTER vi.stubGlobal is set up, so runSandbox sees the fake.
import { runSandbox } from '../sandboxHost'

describe('runSandbox', () => {
  it('resolves with the worker response and terminates the worker', async () => {
    const promise = runSandbox('console.log("hi")', 5000, 4096)
    // Next tick: the worker has been constructed and postMessage called.
    await Promise.resolve()
    expect(currentWorker).not.toBeNull()
    expect(currentWorker!.postedMessages).toHaveLength(1)

    currentWorker!.emitMessage({ stdout: 'hi', error: null })

    const result = await promise
    expect(result).toEqual({ stdout: 'hi', error: null })
    expect(currentWorker!.terminated).toBe(true)
  })

  it('resolves with a timeout error and terminates the worker', async () => {
    vi.useFakeTimers()
    try {
      const promise = runSandbox('while(true){}', 150, 4096)
      // Allow microtasks to flush so the worker is constructed.
      await Promise.resolve()
      expect(currentWorker).not.toBeNull()

      // Fast-forward past the timeout.
      vi.advanceTimersByTime(200)

      const result = await promise
      expect(result).toEqual({
        stdout: '',
        error: 'Client-side timeout after 150ms',
      })
      expect(currentWorker!.terminated).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('resolves with a crash error when the worker emits error', async () => {
    const promise = runSandbox('x', 5000, 4096)
    await Promise.resolve()
    expect(currentWorker).not.toBeNull()

    currentWorker!.emitError('unexpected runtime')

    const result = await promise
    expect(result.stdout).toBe('')
    expect(result.error).toMatch(/Sandbox crash: unexpected runtime/)
    expect(currentWorker!.terminated).toBe(true)
  })
})
