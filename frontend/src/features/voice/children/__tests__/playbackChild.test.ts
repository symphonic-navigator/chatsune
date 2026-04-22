import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: {
    setCurrentToken: vi.fn(),
    setCallbacks: vi.fn(),
    closeStream: vi.fn(),
    clearScope: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
  },
}))

import { createPlaybackChild } from '../playbackChild'
import { audioPlayback } from '../../infrastructure/audioPlayback'

describe('playbackChild', () => {
  beforeEach(() => {
    ;(audioPlayback.setCurrentToken as any).mockClear()
    ;(audioPlayback.setCallbacks as any).mockClear()
    ;(audioPlayback.clearScope as any).mockClear()
    ;(audioPlayback.pause as any).mockClear()
    ;(audioPlayback.resume as any).mockClear()
  })

  it('sets current token on creation', () => {
    createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    expect(audioPlayback.setCurrentToken).toHaveBeenCalledWith('c1')
  })

  it('clearScope + null-token on cancel with matching token', () => {
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    ;(audioPlayback.setCurrentToken as any).mockClear() // don't count the constructor call
    child.onCancel('user-stop', 'c1')
    expect(audioPlayback.setCurrentToken).toHaveBeenLastCalledWith(null)
    expect(audioPlayback.clearScope).toHaveBeenCalledWith('c1')
  })

  it('onCancel calls clearScope before setCurrentToken(null)', () => {
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    const order: string[] = []
    ;(audioPlayback.clearScope as any).mockImplementation(() => { order.push('clearScope') })
    ;(audioPlayback.setCurrentToken as any).mockImplementation((t: unknown) => {
      if (t === null) order.push('setCurrentTokenNull')
    })
    order.length = 0 // drop any calls from constructor
    child.onCancel('user-stop', 'c1')
    expect(order).toEqual(['clearScope', 'setCurrentTokenNull'])
  })

  it('onCancel is a no-op for wrong token', () => {
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    ;(audioPlayback.clearScope as any).mockClear()
    child.onCancel('user-stop', 'other')
    expect(audioPlayback.clearScope).not.toHaveBeenCalled()
  })

  it('onPause calls audioPlayback.pause()', () => {
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    child.onPause!()
    expect(audioPlayback.pause).toHaveBeenCalledTimes(1)
  })

  it('onResume calls audioPlayback.resume()', () => {
    const child = createPlaybackChild({ correlationId: 'c1', gapMs: 0 })
    child.onResume!()
    expect(audioPlayback.resume).toHaveBeenCalledTimes(1)
  })
})
