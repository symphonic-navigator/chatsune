import { describe, it, expect, vi } from 'vitest'

vi.mock('../../voice/infrastructure/audioPlayback', () => ({
  audioPlayback: {
    setCurrentToken: vi.fn(),
    setCallbacks: vi.fn(),
    closeStream: vi.fn(),
    clearScope: vi.fn(),
    enqueue: vi.fn(),
  },
}))

vi.mock('../../../core/store/chatStore', () => ({
  useChatStore: {
    getState: vi.fn(() => ({
      startStreaming: vi.fn(),
      appendStreamingContent: vi.fn(),
      cancelStreaming: vi.fn(),
    })),
  },
}))

import { buildChildren } from '../buildChildren'

describe('buildChildren', () => {
  it('text mode returns only chatStoreSink', () => {
    const children = buildChildren({
      correlationId: 'c1', sessionId: 's1', mode: 'text',
    })
    expect(children.map((c) => c.name)).toEqual(['chatStoreSink'])
  })

  it('voice mode returns full chain', () => {
    const fakeTts: any = {
      synthesise: vi.fn().mockResolvedValue(new ArrayBuffer(0)),
      voices: [],
      isReady: vi.fn().mockReturnValue(true),
    }
    const children = buildChildren({
      correlationId: 'c1', sessionId: 's1', mode: 'voice',
      voice: {
        tts: fakeTts,
        voice: {} as any,
        narratorVoice: {} as any,
        narratorMode: 'dialogue' as any,
        modulation: {
          dialogue_speed: 1.0,
          dialogue_pitch: 0,
          narrator_speed: 1.0,
          narrator_pitch: 0,
        },
        gapMs: 100,
        narratorEnabled: true,
      },
    })
    expect(children.map((c) => c.name)).toEqual([
      'chatStoreSink', 'sentencer', 'pauser', 'synth', 'playback',
    ])
  })
})
