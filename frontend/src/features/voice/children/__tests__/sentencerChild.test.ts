import { describe, it, expect, vi } from 'vitest'
import { createSentencerChild } from '../sentencerChild'

describe('sentencerChild', () => {
  it('pushes delta to underlying sentencer and emits segments to subscribers', () => {
    const pushed: string[] = []
    const fakeSentencer = {
      push: vi.fn((d: string) => { pushed.push(d); return [] }),
      flush: vi.fn(() => []),
    }
    const onSegment = vi.fn()
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment,
    })
    child.onDelta('hello.', 'c1')
    expect(fakeSentencer.push).toHaveBeenCalledWith('hello.')
  })

  it('emits segments from push() result to onSegment subscribers', () => {
    const seg = { text: 'hello.', speed: 1, pitch: 0 } as any
    const fakeSentencer = {
      push: vi.fn(() => [seg]),
      flush: vi.fn(() => []),
    }
    const onSegment = vi.fn()
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment,
    })
    child.onDelta('hello.', 'c1')
    expect(onSegment).toHaveBeenCalledWith(seg, 'c1')
  })

  it('drops onDelta when token does not match', () => {
    const fakeSentencer = {
      push: vi.fn(() => []),
      flush: vi.fn(() => []),
    }
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment: vi.fn(),
    })
    child.onDelta('hello', 'other-token')
    expect(fakeSentencer.push).not.toHaveBeenCalled()
  })

  it('onStreamEnd flushes the sentencer and emits remaining segments', async () => {
    const seg = { text: 'tail', speed: 1, pitch: 0 } as any
    const fakeSentencer = {
      push: vi.fn(() => []),
      flush: vi.fn(() => [seg]),
    }
    const onSegment = vi.fn()
    const child = createSentencerChild({
      correlationId: 'c1',
      sentencer: fakeSentencer as any,
      onSegment,
    })
    await child.onStreamEnd('c1')
    expect(fakeSentencer.flush).toHaveBeenCalled()
    expect(onSegment).toHaveBeenCalledWith(seg, 'c1')
  })
})
