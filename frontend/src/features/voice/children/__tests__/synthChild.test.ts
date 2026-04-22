import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: { enqueue: vi.fn() },
}))

import { createSynthChild } from '../synthChild'
import { audioPlayback } from '../../infrastructure/audioPlayback'

describe('synthChild', () => {
  beforeEach(() => {
    ;(audioPlayback.enqueue as any).mockClear()
  })

  it('synthesises and enqueues when token matches', async () => {
    const audio = new Float32Array(100)
    const fakeTts: any = { synthesise: vi.fn().mockResolvedValue(audio) }
    const child = createSynthChild({
      correlationId: 'c1',
      tts: fakeTts,
      voice: {} as any,
      narratorVoice: {} as any,
      mode: 'dialogue' as any,
      modulation: { dialogue_speed: 1, dialogue_pitch: 0, narrator_speed: 1, narrator_pitch: 0 },
    })
    const seg = { type: 'voice', text: 'hi', speed: 1, pitch: 0 } as any
    await child.enqueueSegment(seg, 'c1')
    expect(fakeTts.synthesise).toHaveBeenCalled()
    expect(audioPlayback.enqueue).toHaveBeenCalledWith(audio, seg, 'c1')
  })

  it('skips enqueue after onCancel', async () => {
    const audio = new Float32Array(100)
    const fakeTts: any = { synthesise: vi.fn().mockResolvedValue(audio) }
    const child = createSynthChild({
      correlationId: 'c1',
      tts: fakeTts,
      voice: {} as any,
      narratorVoice: {} as any,
      mode: 'dialogue' as any,
      modulation: { dialogue_speed: 1, dialogue_pitch: 0, narrator_speed: 1, narrator_pitch: 0 },
    })
    child.onCancel('user-stop', 'c1')
    const seg = { type: 'voice', text: 'hi', speed: 1, pitch: 0 } as any
    await child.enqueueSegment(seg, 'c1')
    expect(audioPlayback.enqueue).not.toHaveBeenCalled()
  })

  it('drops enqueueSegment with wrong token', async () => {
    const fakeTts: any = { synthesise: vi.fn() }
    const child = createSynthChild({
      correlationId: 'c1',
      tts: fakeTts,
      voice: {} as any,
      narratorVoice: {} as any,
      mode: 'dialogue' as any,
      modulation: { dialogue_speed: 1, dialogue_pitch: 0, narrator_speed: 1, narrator_pitch: 0 },
    })
    await child.enqueueSegment({ type: 'voice', text: 'hi', speed: 1, pitch: 0 } as any, 'other-token')
    expect(fakeTts.synthesise).not.toHaveBeenCalled()
  })
})
