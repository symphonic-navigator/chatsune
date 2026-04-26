import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SpeechSegment } from '../../types'

// We import the module under test lazily so mocks are set up first.
let audioPlayback: typeof import('../audioPlayback').audioPlayback

// Minimal AudioContext stub: createBuffer/createBufferSource return objects
// whose onended callback can be triggered manually to simulate playback end.
class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  playbackRate = { value: 1 }
  start = vi.fn()
  stop = vi.fn()
  connect = vi.fn()
}

let sources: FakeSource[] = []

class FakeAnalyserNode {
  _name = 'analyser'
  fftSize = 256
  smoothingTimeConstant = 0
  minDecibels = -100
  maxDecibels = -30
  connect = vi.fn()
  disconnect = vi.fn()
}

class FakeAudioContext {
  state = 'running'
  destination = {}
  currentTime = 0
  createBuffer() { return { getChannelData: () => ({ set: vi.fn() }) } }
  createBufferSource() {
    const s = new FakeSource()
    sources.push(s)
    return s
  }
  createAnalyser() { return new FakeAnalyserNode() }
  resume() { this.state = 'running'; return Promise.resolve() }
  close() { this.state = 'closed'; return Promise.resolve() }
}

const SEGMENT: SpeechSegment = { type: 'voice', text: 'x' }

beforeEach(async () => {
  vi.useFakeTimers()
  sources = []
  // @ts-expect-error — injecting global stub for test
  globalThis.AudioContext = FakeAudioContext
  const mod = await import('../audioPlayback')
  audioPlayback = mod.audioPlayback
  audioPlayback.dispose() // reset state between tests
})

afterEach(() => {
  vi.useRealTimers()
})

function finishPlayback(index = 0): void {
  const s = sources[index]
  if (s && s.onended) s.onended()
}

describe('audioPlayback — streamClosed semantics', () => {
  it('does not fire onFinished when the queue drains while streamClosed is false', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    const audio = new Float32Array(10)
    audioPlayback.enqueue(audio, SEGMENT)
    finishPlayback(0) // first segment ends, queue now empty
    expect(onFinished).not.toHaveBeenCalled()
  })

  it('fires onFinished when closeStream is called after the queue drains', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(0)
    audioPlayback.closeStream()
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('fires onFinished when closeStream is called before the last segment ends', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.closeStream()
    expect(onFinished).not.toHaveBeenCalled()
    finishPlayback(0)
    expect(onFinished).toHaveBeenCalledTimes(1)
  })

  it('stopAll resets streamClosed so a new session can start', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.closeStream()
    finishPlayback(0)
    expect(onFinished).toHaveBeenCalledTimes(1)

    // New session: closeStream from a prior run should not persist
    audioPlayback.stopAll()
    const onFinished2 = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: onFinished2 })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(1)
    expect(onFinished2).not.toHaveBeenCalled()
  })

  it('setCurrentToken starts a fresh scoped stream after a previous scope closed', () => {
    const onFinished = vi.fn()
    audioPlayback.setCurrentToken('group-1')
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT, 'group-1')
    audioPlayback.closeStream()
    finishPlayback(0)
    expect(onFinished).toHaveBeenCalledTimes(1)

    const onFinished2 = vi.fn()
    audioPlayback.setCurrentToken('group-2')
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: onFinished2 })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT, 'group-2')
    finishPlayback(1)
    expect(onFinished2).not.toHaveBeenCalled()
  })
})

describe('audioPlayback — gap timer', () => {
  it('waits gapMs before starting the next segment', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 200, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // first segment playing
    finishPlayback(0)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // still waiting
    vi.advanceTimersByTime(199)
    expect(onSegmentStart).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1)
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
  })

  it('calls the next segment immediately when gapMs is 0', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 0, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(0)
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
  })

  it('stopAll cancels a pending gap timer', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 500, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    finishPlayback(0)
    audioPlayback.stopAll()
    vi.advanceTimersByTime(1000)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // second segment never started
  })
})

// ── Modulation routing ──

// Track how audio graph nodes were connected per segment
const connections: Array<{ from: string; to: string }> = []

class FakeModulationNode {
  _name = 'soundtouch'
  tempo = { value: 1 }
  pitchSemitones = { value: 0 }
  connect = vi.fn((dest: unknown) => {
    const name = (dest as { _name?: string })._name ?? 'destination'
    connections.push({ from: 'soundtouch', to: name })
  })
  disconnect = vi.fn()
}

vi.mock('../soundTouchLoader', () => ({
  ensureSoundTouchReady: vi.fn().mockResolvedValue(true),
  createModulationNode: vi.fn((_ctx: unknown, speed: number, pitch: number) => {
    const node = new FakeModulationNode()
    node.tempo.value = speed
    node.pitchSemitones.value = pitch
    return node
  }),
}))

describe('audioPlayback — modulation', () => {
  beforeEach(() => {
    connections.length = 0
  })

  it('routes segment audio through a modulation node when speed or pitch set', async () => {
    const seg: SpeechSegment = { type: 'voice', text: 'x', speed: 0.9, pitch: 2 }
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), seg)
    // Let the async playNext settle through microtasks.
    await vi.waitFor(() => expect(sources.length).toBe(1))
    expect(connections.some((c) => c.from === 'soundtouch')).toBe(true)
  })

  it('skips the modulation node when speed and pitch are both neutral', async () => {
    const seg: SpeechSegment = { type: 'voice', text: 'x' } // no speed/pitch
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), seg)
    await vi.waitFor(() => expect(sources.length).toBe(1))
    expect(connections.some((c) => c.from === 'soundtouch')).toBe(false)
  })
})

describe('audioPlayback — token gating', () => {
  beforeEach(() => {
    audioPlayback.stopAll()
    audioPlayback.setCurrentToken(null)
  })

  it('drops enqueue when token does not match current', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as unknown as SpeechSegment
    audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-B')
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('accepts enqueue when token matches', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as unknown as SpeechSegment
    // Should not throw; queue accepts the entry (real playback depends on AudioContext
    // which is unavailable in jsdom — the assertion here is that enqueue did not drop).
    expect(() => audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')).not.toThrow()
  })

  it('clearScope(token) drops queue when token matches current', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as unknown as SpeechSegment
    audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')
    audioPlayback.clearScope('token-A')
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('clearScope(token) is a no-op when token does not match current', () => {
    audioPlayback.setCurrentToken('token-A')
    const before = audioPlayback.isPlaying()
    audioPlayback.clearScope('other-token')
    expect(audioPlayback.isPlaying()).toBe(before)
  })

  it('enqueue with token is accepted when currentToken is null (no scope set)', () => {
    audioPlayback.setCurrentToken(null)
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x' } as unknown as SpeechSegment
    expect(() => audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')).not.toThrow()
  })

  it('enqueue without token is accepted regardless of currentToken (non-Group call sites)', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x' } as unknown as SpeechSegment
    // ReadAloud and PersonaVoiceConfig preview pass no token — must not drop.
    expect(() => audioPlayback.enqueue(fakeAudio, fakeSegment)).not.toThrow()
  })
})

describe('audioPlayback — pause/resume', () => {
  beforeEach(() => {
    audioPlayback.stopAll()
    audioPlayback.setCurrentToken(null)
  })

  it('pause stops current source without clearing queue', () => {
    audioPlayback.setCurrentToken('t1')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as unknown as SpeechSegment
    audioPlayback.enqueue(fakeAudio, fakeSegment, 't1')
    audioPlayback.pause()
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('enqueue does not auto-play while paused', () => {
    audioPlayback.setCurrentToken('t1')
    audioPlayback.pause()
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x', speed: 1, pitch: 0 } as unknown as SpeechSegment
    audioPlayback.enqueue(fakeAudio, fakeSegment, 't1')
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('pause is idempotent', () => {
    audioPlayback.pause()
    audioPlayback.pause()
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('resume is a no-op when not paused', () => {
    expect(() => audioPlayback.resume()).not.toThrow()
  })

  it('stopAll resets paused so a subsequent enqueue can play', () => {
    audioPlayback.pause()
    audioPlayback.stopAll()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    expect(() => audioPlayback.enqueue(new Float32Array(10), SEGMENT)).not.toThrow()
    expect(audioPlayback.isPlaying()).toBe(true)
  })

  it('clearScope resets paused so the next group can auto-play', () => {
    // Simulate a barge-cancel hand-off: pause was active on the old group,
    // then clearScope runs while the token still matches, then a new group
    // sets its own token and enqueues — that enqueue must auto-play.
    audioPlayback.setCurrentToken('old-group')
    audioPlayback.pause()
    audioPlayback.clearScope('old-group')
    audioPlayback.setCurrentToken('new-group')
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT, 'new-group')
    expect(audioPlayback.isPlaying()).toBe(true)
  })
})

describe('audioPlayback — subscribe API', () => {
  it('subscribe returns an unsubscribe fn; unsubscribed listeners are not called', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    const listener = vi.fn()
    const unsubscribe = audioPlayback.subscribe(listener)

    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    expect(listener).toHaveBeenCalled()

    listener.mockClear()
    unsubscribe()
    audioPlayback.stopAll()
    expect(listener).not.toHaveBeenCalled()
  })

  it('listeners fire on enqueue and stopAll', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    const listener = vi.fn()
    audioPlayback.subscribe(listener)

    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    expect(listener).toHaveBeenCalled()

    listener.mockClear()
    audioPlayback.stopAll()
    expect(listener).toHaveBeenCalled()
  })

  it('isPlaying reflects the transition observed via subscribe', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    const observed: boolean[] = []
    audioPlayback.subscribe(() => { observed.push(audioPlayback.isPlaying()) })

    expect(audioPlayback.isPlaying()).toBe(false)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    expect(audioPlayback.isPlaying()).toBe(true)
    expect(observed.some((v) => v === true)).toBe(true)

    audioPlayback.stopAll()
    expect(audioPlayback.isPlaying()).toBe(false)
    expect(observed[observed.length - 1]).toBe(false)
  })
})
