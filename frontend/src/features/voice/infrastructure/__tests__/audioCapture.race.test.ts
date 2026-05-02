import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePauseRedemptionStore } from '../../stores/pauseRedemptionStore'

// Manually-controlled MicVAD.new promise. The test harness resolves it after
// arranging the race (start, stop, then resolve).
let resolveMicVad: ((vad: unknown) => void) | null = null
let micVadNewCalls = 0
let lastMockVad: { pause: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; start: ReturnType<typeof vi.fn> } | null = null

vi.mock('@ricky0123/vad-web', () => ({
  MicVAD: {
    new: vi.fn(async (opts: { getStream?: () => Promise<MediaStream> }) => {
      micVadNewCalls += 1
      // Trigger getStream so capturedStream is populated, mirroring real vad-web.
      if (opts.getStream) await opts.getStream()
      const vad = {
        pause: vi.fn(),
        destroy: vi.fn(),
        start: vi.fn(async () => {}),
      }
      lastMockVad = vad
      return new Promise((resolve) => {
        resolveMicVad = (v) => resolve(v ?? vad)
      })
    }),
  },
}))

vi.mock('../audioRecording', () => ({
  pickRecordingMimeType: () => 'audio/webm',
  createRecorder: () => ({}),
}))

vi.mock('../wavEncoder', () => ({
  float32ToWavBlob: () => new Blob([], { type: 'audio/wav' }),
}))

if (typeof globalThis.AudioContext === 'undefined') {
  // @ts-expect-error — minimal jsdom stub; not all methods needed
  globalThis.AudioContext = class {
    createMediaStreamSource() {
      return { connect: () => {} }
    }
    createAnalyser() {
      return { fftSize: 256, frequencyBinCount: 128 }
    }
    close() {}
  }
}

// Track the most-recent stream/track stop spies so tests can assert teardown.
let lastTrackStop: ReturnType<typeof vi.fn> | null = null
let lastStream: { getTracks: () => Array<{ stop: ReturnType<typeof vi.fn> }> } | null = null

if (typeof navigator.mediaDevices === 'undefined') {
  Object.defineProperty(navigator, 'mediaDevices', {
    value: {
      getUserMedia: vi.fn(async () => {
        const stop = vi.fn()
        lastTrackStop = stop
        const stream = { getTracks: () => [{ stop }] }
        lastStream = stream
        return stream
      }),
    },
    configurable: true,
  })
} else {
  // Override existing definition for this test file.
  ;(navigator.mediaDevices as unknown as { getUserMedia: () => Promise<unknown> }).getUserMedia = vi.fn(async () => {
    const stop = vi.fn()
    lastTrackStop = stop
    const stream = { getTracks: () => [{ stop }] }
    lastStream = stream
    return stream
  })
}

import { AudioCapture } from '../audioCapture'

describe('audioCapture race — orphan MicVAD discard', () => {
  let capture: AudioCapture

  beforeEach(() => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    resolveMicVad = null
    lastMockVad = null
    lastTrackStop = null
    lastStream = null
    micVadNewCalls = 0
    capture = new AudioCapture()
  })

  it('discards the orphan VAD when stopContinuous lands during MicVAD.new', async () => {
    const startPromise = capture.startContinuous(
      { onSpeechStart: () => {}, onSpeechEnd: () => {}, onVolumeChange: () => {}, onMisfire: () => {} },
      { threshold: 'medium', redemptionMs: 1728 },
    )

    // Wait a microtask so getStream resolves and captures the MediaStream
    // before stopContinuous arrives — mirrors the real-world ordering where
    // the mic stream opens fast but model download is the slow step.
    await Promise.resolve()
    await Promise.resolve()

    // stopContinuous fires while MicVAD.new is still pending.
    capture.stopContinuous()

    // Now the model "finishes downloading" and MicVAD.new resolves.
    expect(resolveMicVad).not.toBeNull()
    resolveMicVad!(undefined)

    await startPromise

    // Orphan must have been torn down.
    expect(lastMockVad).not.toBeNull()
    expect(lastMockVad!.destroy).toHaveBeenCalledTimes(1)
    expect(lastMockVad!.start).not.toHaveBeenCalled()

    // Captured stream tracks must have been stopped by the orphan path.
    expect(lastTrackStop).not.toBeNull()
    expect(lastTrackStop!).toHaveBeenCalled()

    // No public stream surface should be exposed.
    expect(capture.getMediaStream()).toBeNull()

    // Internal vad slot must remain null.
    expect((capture as unknown as { vad: unknown }).vad).toBeNull()
  })

  it('happy path: starts VAD normally without a concurrent stop', async () => {
    const startPromise = capture.startContinuous(
      { onSpeechStart: () => {}, onSpeechEnd: () => {}, onVolumeChange: () => {}, onMisfire: () => {} },
      { threshold: 'medium', redemptionMs: 1728 },
    )

    await Promise.resolve()
    await Promise.resolve()

    expect(resolveMicVad).not.toBeNull()
    resolveMicVad!(undefined)

    await startPromise

    expect(lastMockVad).not.toBeNull()
    expect(lastMockVad!.start).toHaveBeenCalledTimes(1)
    expect(lastMockVad!.destroy).not.toHaveBeenCalled()
    expect(capture.getMediaStream()).toBe(lastStream)
    expect((capture as unknown as { vad: unknown }).vad).toBe(lastMockVad)
  })

  it('only one MicVAD instance is constructed during a start/stop race', async () => {
    const startPromise = capture.startContinuous(
      { onSpeechStart: () => {}, onSpeechEnd: () => {}, onVolumeChange: () => {}, onMisfire: () => {} },
      { threshold: 'medium', redemptionMs: 1728 },
    )

    await Promise.resolve()
    await Promise.resolve()

    capture.stopContinuous()
    resolveMicVad!(undefined)
    await startPromise

    expect(micVadNewCalls).toBe(1)
  })
})
