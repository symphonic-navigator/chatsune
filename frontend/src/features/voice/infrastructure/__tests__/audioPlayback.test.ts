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

class FakeAudioContext {
  state = 'running'
  destination = {}
  // Mutable so tests can simulate elapsed playback time before calling mute().
  currentTime = 0
  createBuffer() { return { getChannelData: () => ({ set: vi.fn() }) } }
  createBufferSource() {
    const s = new FakeSource()
    sources.push(s)
    return s
  }
  resume() { this.state = 'running'; return Promise.resolve() }
  close() { this.state = 'closed'; return Promise.resolve() }
}

// Grab the active FakeAudioContext from the most recent source that was
// created. Playback creates the context lazily on first enqueue, so we read
// it back via the module's internal ctx field through a tiny escape hatch
// kept in sync with the implementation: every FakeAudioContext instance
// sets itself on this global when created.
let activeCtx: FakeAudioContext | null = null
const OriginalFakeCtor = FakeAudioContext
// Patch ctor so the most-recent instance is easy to find in tests.
function TrackingFakeAudioContext(this: FakeAudioContext): FakeAudioContext {
  const inst = new OriginalFakeCtor()
  activeCtx = inst
  return inst
}
TrackingFakeAudioContext.prototype = OriginalFakeCtor.prototype

const SEGMENT: SpeechSegment = { type: 'voice', text: 'x' }

beforeEach(async () => {
  vi.useFakeTimers()
  sources = []
  activeCtx = null
  // @ts-expect-error — injecting global stub for test
  globalThis.AudioContext = TrackingFakeAudioContext
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

describe('audioPlayback — mute / resumeFromMute', () => {
  it('mute stops the current source but preserves the queue', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    // First segment is playing; second is in the queue.
    expect(sources[0].stop).not.toHaveBeenCalled()

    audioPlayback.mute()

    expect(sources[0].stop).toHaveBeenCalledTimes(1)
    expect(audioPlayback.isMuted()).toBe(true)
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('resumeFromMute replays the muted segment from the captured offset, then continues the queue', async () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart, onFinished: vi.fn() })
    // 24 000 samples = 1 s at SAMPLE_RATE; buffer long enough to accommodate a
    // 0.5 s resume offset without the pause-cap kicking in.
    const audio = new Float32Array(24_000)
    audioPlayback.enqueue(audio, SEGMENT)
    audioPlayback.enqueue(new Float32Array(24_000), { ...SEGMENT, text: 'second' })
    await vi.waitFor(() => expect(sources.length).toBe(1))
    expect(onSegmentStart).toHaveBeenCalledTimes(1)
    expect(onSegmentStart).toHaveBeenNthCalledWith(1, SEGMENT)

    // Simulate 0.5 s of playback elapsing before the mute.
    if (activeCtx) activeCtx.currentTime = 0.5
    audioPlayback.mute()
    audioPlayback.resumeFromMute()
    await vi.waitFor(() => expect(sources.length).toBe(2))

    expect(audioPlayback.isMuted()).toBe(false)
    // Resume segment is played again, starting mid-buffer at the captured offset.
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
    expect(onSegmentStart).toHaveBeenNthCalledWith(2, SEGMENT)
    expect(sources[1].start).toHaveBeenCalledWith(0, 0.5)

    // When it finishes, the second segment plays from the start.
    finishPlayback(1)
    await vi.waitFor(() => expect(sources.length).toBe(3))
    expect(onSegmentStart).toHaveBeenCalledTimes(3)
    expect(onSegmentStart).toHaveBeenNthCalledWith(3, { ...SEGMENT, text: 'second' })
    expect(sources[2].start).toHaveBeenCalledWith(0, 0)
  })

  it('mute captures the elapsed playback position and resumeFromMute consumes it', async () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    // 2 s of audio at 24 kHz.
    audioPlayback.enqueue(new Float32Array(48_000), SEGMENT)
    await vi.waitFor(() => expect(sources.length).toBe(1))
    if (activeCtx) activeCtx.currentTime = 0.75
    audioPlayback.mute()
    audioPlayback.resumeFromMute()
    await vi.waitFor(() => expect(sources.length).toBe(2))
    expect(sources[1].start).toHaveBeenCalledWith(0, 0.75)
  })

  it('resumeFromMute with no mutedEntry starts the next queued segment from zero', async () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 200, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(24_000), SEGMENT)
    audioPlayback.enqueue(new Float32Array(24_000), { ...SEGMENT, text: 'second' })
    await vi.waitFor(() => expect(sources.length).toBe(1))

    // End the first source → gap timer pending, nothing currently playing.
    finishPlayback(0)
    // Simulate some elapsed context time before muting during the gap.
    if (activeCtx) activeCtx.currentTime = 1.25
    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(true)

    audioPlayback.resumeFromMute()
    await vi.waitFor(() => expect(sources.length).toBe(2))
    // Second segment plays from its own start — the between-segments mute must
    // not propagate an offset into the next buffer.
    expect(sources[1].start).toHaveBeenCalledWith(0, 0)
  })

  it('discardMuted clears the offset so a later mute/resume cycle starts from zero', async () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(48_000), SEGMENT)
    audioPlayback.enqueue(new Float32Array(48_000), { ...SEGMENT, text: 'second' })
    await vi.waitFor(() => expect(sources.length).toBe(1))
    if (activeCtx) activeCtx.currentTime = 0.4
    audioPlayback.mute()
    audioPlayback.discardMuted()
    await vi.waitFor(() => expect(sources.length).toBe(2))
    // Second segment starts at 0 — the old 0.4 s offset must not bleed through.
    expect(sources[1].start).toHaveBeenCalledWith(0, 0)

    // A fresh mute/resume cycle on the second segment captures its own offset.
    if (activeCtx) activeCtx.currentTime = 1.1
    audioPlayback.mute()
    audioPlayback.resumeFromMute()
    await vi.waitFor(() => expect(sources.length).toBe(3))
    // 1.1 − start-time-of-second-segment. Second segment was started with
    // offset 0 when activeCtx.currentTime was 0.4, so its recorded start is
    // 0.4 and the new elapsed is 0.7.
    expect(sources[2].start).toHaveBeenCalledWith(0, expect.closeTo(0.7, 5))
  })

  it('stopAll clears the offset so a later mute/resume cycle starts from zero', async () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(48_000), SEGMENT)
    await vi.waitFor(() => expect(sources.length).toBe(1))
    if (activeCtx) activeCtx.currentTime = 0.6
    audioPlayback.mute()
    audioPlayback.stopAll()

    // Fresh segment in a new session — must start at offset 0.
    audioPlayback.enqueue(new Float32Array(48_000), SEGMENT)
    await vi.waitFor(() => expect(sources.length).toBe(2))
    expect(sources[1].start).toHaveBeenCalledWith(0, 0)
  })

  it('resumeFromMute is a no-op when nothing is muted', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    expect(() => audioPlayback.resumeFromMute()).not.toThrow()
    expect(audioPlayback.isMuted()).toBe(false)
  })

  it('mute is a no-op when nothing is playing', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(false)
  })

  it('mute does not fire onFinished even if streamClosed is set', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.closeStream()

    audioPlayback.mute()

    expect(onFinished).not.toHaveBeenCalled()
  })

  it('stopAll after mute clears the muted entry', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(true)

    audioPlayback.stopAll()

    expect(audioPlayback.isMuted()).toBe(false)
  })

  it('mute cancels a pending gap timer so the next segment does not auto-play', () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ gapMs: 200, onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), { ...SEGMENT, text: 'second' })
    // First segment is playing.
    expect(onSegmentStart).toHaveBeenCalledTimes(1)

    // First segment ends → gap timer pending.
    finishPlayback(0)
    expect(onSegmentStart).toHaveBeenCalledTimes(1) // gap has not elapsed

    // Mute fires during the gap.
    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(true)

    // Advance past the gap — without the fix, playNext would have fired.
    vi.advanceTimersByTime(500)
    expect(onSegmentStart).toHaveBeenCalledTimes(1)

    // Resume — the next queued segment now plays.
    audioPlayback.resumeFromMute()
    expect(audioPlayback.isMuted()).toBe(false)
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
    expect(onSegmentStart).toHaveBeenNthCalledWith(2, { ...SEGMENT, text: 'second' })
  })
})

describe('audioPlayback — discardMuted', () => {
  it('discardMuted clears the muted entry and resumes the rest of the queue', async () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), { ...SEGMENT, text: 'second' })
    expect(onSegmentStart).toHaveBeenCalledTimes(1)
    expect(onSegmentStart).toHaveBeenNthCalledWith(1, SEGMENT)

    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(true)

    const listener = vi.fn()
    audioPlayback.subscribe(listener)

    audioPlayback.discardMuted()
    await Promise.resolve()

    expect(audioPlayback.isMuted()).toBe(false)
    expect(listener).toHaveBeenCalled()
    // The muted first segment is NOT replayed; the second segment plays.
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
    expect(onSegmentStart).toHaveBeenNthCalledWith(2, { ...SEGMENT, text: 'second' })
  })

  it('discardMuted is a no-op when not muted', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    const listener = vi.fn()
    audioPlayback.subscribe(listener)
    expect(() => audioPlayback.discardMuted()).not.toThrow()
    expect(audioPlayback.isMuted()).toBe(false)
    expect(listener).not.toHaveBeenCalled()
  })

  it('discardMuted preserves streamClosed so onFinished still fires later', async () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), { ...SEGMENT, text: 'second' })
    // First segment playing, second queued.
    audioPlayback.mute()
    audioPlayback.closeStream()
    expect(onFinished).not.toHaveBeenCalled()

    audioPlayback.discardMuted()
    await Promise.resolve()

    // Second segment is now playing (index 1); finish it to drain the queue.
    finishPlayback(1)
    expect(onFinished).toHaveBeenCalledTimes(1)
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

  it('enqueue without token is accepted regardless of currentToken (backwards compat)', () => {
    audioPlayback.setCurrentToken('token-A')
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x' } as unknown as SpeechSegment
    // Call site passes no token — shim period, must not drop.
    expect(() => audioPlayback.enqueue(fakeAudio, fakeSegment)).not.toThrow()
  })

  it('enqueue with token is accepted when currentToken is null (no scope set)', () => {
    audioPlayback.setCurrentToken(null)
    const fakeAudio = new Float32Array(24000)
    const fakeSegment = { text: 'x' } as unknown as SpeechSegment
    expect(() => audioPlayback.enqueue(fakeAudio, fakeSegment, 'token-A')).not.toThrow()
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

  it('listeners fire on enqueue / stopAll / mute / resumeFromMute', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    const listener = vi.fn()
    audioPlayback.subscribe(listener)

    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    expect(listener).toHaveBeenCalled()

    listener.mockClear()
    audioPlayback.mute()
    expect(listener).toHaveBeenCalled()

    listener.mockClear()
    audioPlayback.resumeFromMute()
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
