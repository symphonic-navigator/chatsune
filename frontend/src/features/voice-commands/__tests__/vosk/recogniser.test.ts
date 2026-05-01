import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

// Mock vosk-browser with controllable behaviour per test.
// vi.mock is hoisted to the top of the file, so the factory cannot close
// over local variables — use vi.hoisted to share the mocks with the tests.
const {
  mockAcceptWaveform,
  mockFinalResult,
  mockRemove,
  mockKaldiRecognizer,
  mockModel,
  mockDispatch,
} = vi.hoisted(() => {
  const mockAcceptWaveform = vi.fn()
  const mockFinalResult = vi.fn()
  const mockRemove = vi.fn()
  // Use a plain function (not an arrow) so vitest's spy can invoke it
  // via Reflect.construct when the recogniser does `new KaldiRecognizer(...)`.
  const mockKaldiRecognizer = vi.fn(function MockKaldiRecognizer(this: unknown) {
    return {
      acceptWaveform: mockAcceptWaveform,
      finalResult: mockFinalResult,
      remove: mockRemove,
    }
  })
  const mockModel = vi.fn().mockResolvedValue({ /* opaque model handle */ })
  const mockDispatch = vi.fn()
  return {
    mockAcceptWaveform,
    mockFinalResult,
    mockRemove,
    mockKaldiRecognizer,
    mockModel,
    mockDispatch,
  }
})

vi.mock('vosk-browser', () => ({
  createModel: mockModel,
  KaldiRecognizer: mockKaldiRecognizer,
}))

// Mock tryDispatchCommand — recogniser routes successful matches through it.
vi.mock('../../dispatcher', () => ({
  tryDispatchCommand: mockDispatch,
}))

import { vosk } from '../../vosk/recogniser'

describe('vosk recogniser', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vosk.dispose()  // reset state between tests
  })

  afterEach(() => {
    vosk.dispose()
  })

  it('starts in idle state', () => {
    expect(vosk.getState()).toBe('idle')
  })

  it('init transitions to ready and constructs recogniser with grammar', async () => {
    await vosk.init()
    expect(vosk.getState()).toBe('ready')
    expect(mockKaldiRecognizer).toHaveBeenCalled()
  })

  it('init is idempotent — second call is a no-op when ready', async () => {
    await vosk.init()
    const callsAfterFirst = mockKaldiRecognizer.mock.calls.length
    await vosk.init()
    expect(mockKaldiRecognizer.mock.calls.length).toBe(callsAfterFirst)
  })

  it('feed drops silently when state is not ready', () => {
    // not initialised; state === 'idle'
    vosk.feed(new Float32Array(1000))
    expect(mockAcceptWaveform).not.toHaveBeenCalled()
  })

  it('feed drops segments longer than 4 seconds', async () => {
    await vosk.init()
    const fiveSecondsAt16kHz = 5 * 16_000
    vosk.feed(new Float32Array(fiveSecondsAt16kHz))
    expect(mockAcceptWaveform).not.toHaveBeenCalled()
  })

  it('feed accepts segments under 4 seconds and dispatches on accept', async () => {
    await vosk.init()
    mockFinalResult.mockReturnValue({
      text: 'companion on',
      result: [{ word: 'companion', conf: 0.97 }, { word: 'on', conf: 0.96 }],
    })
    vosk.feed(new Float32Array(1 * 16_000))  // 1 second
    expect(mockAcceptWaveform).toHaveBeenCalled()
    expect(mockDispatch).toHaveBeenCalledWith('companion on')
  })

  it('feed rejects when text is not in ACCEPT_TEXTS', async () => {
    await vosk.init()
    mockFinalResult.mockReturnValue({
      text: 'campaign on',
      result: [{ word: 'campaign', conf: 0.99 }, { word: 'on', conf: 0.99 }],
    })
    vosk.feed(new Float32Array(1 * 16_000))
    expect(mockDispatch).not.toHaveBeenCalled()
  })

  it('feed rejects when any per-word confidence is below 0.95', async () => {
    await vosk.init()
    mockFinalResult.mockReturnValue({
      text: 'companion on',
      result: [{ word: 'companion', conf: 0.97 }, { word: 'on', conf: 0.94 }],
    })
    vosk.feed(new Float32Array(1 * 16_000))
    expect(mockDispatch).not.toHaveBeenCalled()
  })

  it('dispose returns to idle state and removes the recogniser', async () => {
    await vosk.init()
    vosk.dispose()
    expect(vosk.getState()).toBe('idle')
    expect(mockRemove).toHaveBeenCalled()
  })

  it('init after dispose rebuilds the recogniser', async () => {
    await vosk.init()
    vosk.dispose()
    const callsBeforeSecondInit = mockKaldiRecognizer.mock.calls.length
    await vosk.init()
    expect(mockKaldiRecognizer.mock.calls.length).toBe(callsBeforeSecondInit + 1)
  })
})
