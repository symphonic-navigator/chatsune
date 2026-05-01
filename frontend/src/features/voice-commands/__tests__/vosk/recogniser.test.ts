import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

// Mock setup: model.KaldiRecognizer is a getter on the Model instance,
// returning an anonymous-class constructor. We simulate the same shape.
const hoisted = vi.hoisted(() => {
  const mockSetWords = vi.fn()
  const mockOn = vi.fn()
  const mockAcceptWaveformFloat = vi.fn()
  const mockRetrieveFinalResult = vi.fn()
  const mockRemove = vi.fn()
  const mockDispatch = vi.fn()

  // The KaldiRecognizer constructor mock — captures the grammar argument
  // and exposes the recogniser instance back to tests.
  const recogniserInstance = {
    setWords: mockSetWords,
    on: mockOn,
    acceptWaveformFloat: mockAcceptWaveformFloat,
    retrieveFinalResult: mockRetrieveFinalResult,
    remove: mockRemove,
  }
  const recogniserCtor = vi.fn(function MockKaldiRecognizer(this: unknown) {
    return recogniserInstance
  })

  // The Model instance — has a `KaldiRecognizer` getter returning the ctor.
  const modelInstance = {
    KaldiRecognizer: recogniserCtor,
  }

  const mockCreateModel = vi.fn().mockResolvedValue(modelInstance)

  return {
    mockSetWords,
    mockOn,
    mockAcceptWaveformFloat,
    mockRetrieveFinalResult,
    mockRemove,
    recogniserCtor,
    mockCreateModel,
    mockDispatch,
  }
})

vi.mock('vosk-browser', () => ({
  createModel: hoisted.mockCreateModel,
}))

vi.mock('../../dispatcher', () => ({
  tryDispatchCommand: hoisted.mockDispatch,
}))

import { vosk } from '../../vosk/recogniser'

/**
 * Helper: simulate the recogniser firing a 'result' event — extracts the
 * listener registered via recogniser.on('result', listener) and invokes
 * it directly.
 */
function fireResultEvent(payload: unknown): void {
  const onCalls = hoisted.mockOn.mock.calls
  const resultCall = onCalls.find(([event]) => event === 'result')
  if (!resultCall) throw new Error('no result listener registered')
  const listener = resultCall[1] as (msg: unknown) => void
  listener(payload)
}

describe('vosk recogniser', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vosk.dispose()
  })

  afterEach(() => {
    vosk.dispose()
  })

  it('starts in idle state', () => {
    expect(vosk.getState()).toBe('idle')
  })

  it('init transitions to ready, constructs recogniser with grammar, enables words, registers result listener', async () => {
    await vosk.init()
    expect(vosk.getState()).toBe('ready')
    expect(hoisted.recogniserCtor).toHaveBeenCalledWith(
      16000,
      expect.stringContaining('companion on'),
    )

    expect(hoisted.mockSetWords).toHaveBeenCalledWith(true)
    const onCalls = hoisted.mockOn.mock.calls
    expect(onCalls.some(([event]) => event === 'result')).toBe(true)
  })

  it('init is idempotent — second call is a no-op when ready', async () => {
    await vosk.init()
    const callsAfterFirst = hoisted.recogniserCtor.mock.calls.length
    await vosk.init()
    expect(hoisted.recogniserCtor.mock.calls.length).toBe(callsAfterFirst)
  })

  it('feed drops silently when state is not ready', () => {
    vosk.feed(new Float32Array(1000))
    expect(hoisted.mockAcceptWaveformFloat).not.toHaveBeenCalled()
  })

  it('feed drops segments longer than 4 seconds', async () => {
    await vosk.init()
    const fiveSecondsAt16kHz = 5 * 16_000
    vosk.feed(new Float32Array(fiveSecondsAt16kHz))
    expect(hoisted.mockAcceptWaveformFloat).not.toHaveBeenCalled()
  })

  it('feed accepts segments under 4 seconds and forces a final result', async () => {
    await vosk.init()
    vosk.feed(new Float32Array(1 * 16_000))
    expect(hoisted.mockAcceptWaveformFloat).toHaveBeenCalled()
    expect(hoisted.mockRetrieveFinalResult).toHaveBeenCalled()
  })

  it('dispatches when result event has accepted text and all confs >= 0.95', async () => {
    await vosk.init()
    vosk.feed(new Float32Array(1 * 16_000))
    fireResultEvent({
      event: 'result',
      result: {
        text: 'companion on',
        result: [
          { word: 'companion', conf: 0.97 },
          { word: 'on', conf: 0.96 },
        ],
      },
    })
    expect(hoisted.mockDispatch).toHaveBeenCalledWith('companion on')
  })

  it('rejects when text is not in ACCEPT_TEXTS', async () => {
    await vosk.init()
    vosk.feed(new Float32Array(1 * 16_000))
    fireResultEvent({
      event: 'result',
      result: {
        text: 'campaign on',
        result: [
          { word: 'campaign', conf: 0.99 },
          { word: 'on', conf: 0.99 },
        ],
      },
    })
    expect(hoisted.mockDispatch).not.toHaveBeenCalled()
  })

  it('rejects when any per-word conf < 0.95', async () => {
    await vosk.init()
    vosk.feed(new Float32Array(1 * 16_000))
    fireResultEvent({
      event: 'result',
      result: {
        text: 'companion on',
        result: [
          { word: 'companion', conf: 0.97 },
          { word: 'on', conf: 0.94 },
        ],
      },
    })
    expect(hoisted.mockDispatch).not.toHaveBeenCalled()
  })

  it('ignores non-result events', async () => {
    await vosk.init()
    fireResultEvent({ event: 'partialresult', result: { partial: 'compan' } })
    expect(hoisted.mockDispatch).not.toHaveBeenCalled()
  })

  it('dispose returns to idle and calls remove()', async () => {
    await vosk.init()
    vosk.dispose()
    expect(vosk.getState()).toBe('idle')
    expect(hoisted.mockRemove).toHaveBeenCalled()
  })

  it('init after dispose rebuilds the recogniser', async () => {
    await vosk.init()
    vosk.dispose()
    const callsBeforeSecondInit = hoisted.recogniserCtor.mock.calls.length
    await vosk.init()
    expect(hoisted.recogniserCtor.mock.calls.length).toBe(callsBeforeSecondInit + 1)
  })
})
