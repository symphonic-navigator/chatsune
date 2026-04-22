import { describe, it, expect, vi } from 'vitest'
import { createPauserChild } from '../pauserChild'

describe('pauserChild', () => {
  it('forwards segment to onSegmentReleased when token matches', () => {
    const released = vi.fn()
    const pauser = createPauserChild({ correlationId: 'c1', onSegmentReleased: released })
    const seg = { type: 'voice', text: 'a', speed: 1, pitch: 0 } as any
    pauser.pushSegment(seg, 'c1')
    expect(released).toHaveBeenCalledWith(seg, 'c1')
  })

  it('drops segment when token mismatches', () => {
    const released = vi.fn()
    const pauser = createPauserChild({ correlationId: 'c1', onSegmentReleased: released })
    const seg = { type: 'voice', text: 'a', speed: 1, pitch: 0 } as any
    pauser.pushSegment(seg, 'other')
    expect(released).not.toHaveBeenCalled()
  })
})
