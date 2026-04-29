import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePauseRedemptionStore } from '../../stores/pauseRedemptionStore'

// Capture the onFrameProcessed callback that AudioCapture passes into MicVAD,
// then drive it directly to verify the silence-edge state machine.
//
// NOTE: vi.resetModules() runs in beforeEach (see src/test/setup.ts), but
// module-level vi.mock() calls are hoisted by Vitest before any imports,
// so the mock factory below is installed before AudioCapture is loaded.
// The top-level `import { AudioCapture }` below therefore gets the mocked
// MicVAD — fresh instance per test because AudioCapture is instantiated in
// each beforeEach, not at module scope.
let frameProcessed: ((p: { isSpeech: number }) => void) | null = null

vi.mock('@ricky0123/vad-web', () => ({
  MicVAD: {
    new: vi.fn(async (opts: { onFrameProcessed?: (p: { isSpeech: number }) => void }) => {
      frameProcessed = opts.onFrameProcessed ?? null
      return { start: vi.fn(), pause: vi.fn(), destroy: vi.fn() }
    }),
  },
}))

vi.mock('../audioRecording', () => ({
  pickRecordingMimeType: () => 'audio/webm',
  createRecorder: () => ({}),
}))

// The WAV encoder is not exercised by frame state-machine tests; stub it out
// so the import resolves cleanly in jsdom.
vi.mock('../wavEncoder', () => ({
  float32ToWavBlob: () => new Blob([], { type: 'audio/wav' }),
}))

// AudioContext is not available in jsdom. Stub the global so that
// startContinuous's post-VAD AudioContext creation does not throw.
// The volume meter path is not exercised here so a minimal stub is enough.
if (typeof globalThis.AudioContext === 'undefined') {
  // @ts-expect-error — minimal jsdom stub; not all methods needed
  globalThis.AudioContext = class {
    createMediaStreamSource() {
      return { connect: () => {} }
    }
    createAnalyser() {
      return { fftSize: 256, frequencyBinCount: 128 }
    }
  }
}

// getUserMedia is not available in jsdom. The AudioCapture.startContinuous
// call triggers getStream inside MicVAD.new (which the mock intercepts), but
// the capturedStream branch relies on the real getUserMedia being available.
// Install a stub that returns a minimal MediaStream-shaped object so that
// capturedStream is truthy and AudioContext setup proceeds without error.
if (typeof navigator.mediaDevices === 'undefined') {
  Object.defineProperty(navigator, 'mediaDevices', {
    value: {
      getUserMedia: vi.fn(async () => ({
        getTracks: () => [{ stop: () => {} }],
      })),
    },
    configurable: true,
  })
}

import { AudioCapture } from '../audioCapture'

// Medium-preset thresholds (from vadPresets.ts — medium row).
const POSITIVE = 0.65  // medium preset positiveSpeechThreshold
const NEGATIVE = 0.5   // medium preset negativeSpeechThreshold

// Suppress — NEGATIVE and POSITIVE are referenced by name below for clarity
void POSITIVE
void NEGATIVE

describe('audioCapture frame state machine — pauseRedemptionStore edges', () => {
  let capture: AudioCapture

  beforeEach(async () => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    frameProcessed = null
    capture = new AudioCapture()
    await capture.startContinuous(
      { onSpeechStart: () => {}, onSpeechEnd: () => {}, onVolumeChange: () => {}, onMisfire: () => {} },
      { threshold: 'medium', redemptionMs: 1728 },
    )
    expect(frameProcessed).not.toBeNull()
  })

  it('does NOT open redemption while no confirmed speech segment is active', () => {
    // Five low-prob frames, but onSpeechStart was never invoked.
    for (let i = 0; i < 5; i++) frameProcessed!({ isSpeech: 0.1 })
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })

  it('opens redemption only after 4 consecutive sub-negative frames inside speech', () => {
    ;(capture as unknown as { handleVadSpeechStart(): void }).handleVadSpeechStart()
    frameProcessed!({ isSpeech: 0.1 }) // 1
    frameProcessed!({ isSpeech: 0.1 }) // 2
    frameProcessed!({ isSpeech: 0.1 }) // 3
    expect(usePauseRedemptionStore.getState().active).toBe(false) // grace not exhausted yet
    frameProcessed!({ isSpeech: 0.1 }) // 4 — grace exhausted, window opens
    expect(usePauseRedemptionStore.getState().active).toBe(true)
    expect(usePauseRedemptionStore.getState().windowMs).toBe(1728)
  })

  it('a single high-prob frame inside the grace window resets the silence counter', () => {
    ;(capture as unknown as { handleVadSpeechStart(): void }).handleVadSpeechStart()
    frameProcessed!({ isSpeech: 0.1 }) // 1
    frameProcessed!({ isSpeech: 0.1 }) // 2
    frameProcessed!({ isSpeech: 0.9 }) // resumed — counter resets to 0
    frameProcessed!({ isSpeech: 0.1 }) // 1 again
    frameProcessed!({ isSpeech: 0.1 }) // 2
    frameProcessed!({ isSpeech: 0.1 }) // 3
    expect(usePauseRedemptionStore.getState().active).toBe(false)
    frameProcessed!({ isSpeech: 0.1 }) // 4 — now opens
    expect(usePauseRedemptionStore.getState().active).toBe(true)
  })

  it('high-prob frame after redemption opened closes it again', () => {
    ;(capture as unknown as { handleVadSpeechStart(): void }).handleVadSpeechStart()
    for (let i = 0; i < 4; i++) frameProcessed!({ isSpeech: 0.1 })
    expect(usePauseRedemptionStore.getState().active).toBe(true)

    frameProcessed!({ isSpeech: 0.9 })
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })

  it('handleVadSpeechEnd clears redemption (idempotent)', () => {
    ;(capture as unknown as { handleVadSpeechStart(): void }).handleVadSpeechStart()
    for (let i = 0; i < 4; i++) frameProcessed!({ isSpeech: 0.1 })
    ;(capture as unknown as { handleVadSpeechEnd(pcm: Float32Array): void }).handleVadSpeechEnd(new Float32Array(0))
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })

  it('handleVadMisfire clears redemption', () => {
    ;(capture as unknown as { handleVadSpeechStart(): void }).handleVadSpeechStart()
    for (let i = 0; i < 4; i++) frameProcessed!({ isSpeech: 0.1 })
    ;(capture as unknown as { handleVadMisfire(): void }).handleVadMisfire()
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })
})
