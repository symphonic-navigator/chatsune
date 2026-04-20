import { afterEach, describe, expect, it, vi } from 'vitest'
import { pickRecordingMimeType, extensionForMimeType } from '../audioRecording'

// jsdom does not provide MediaRecorder. We stub the global for each test,
// reflecting the scenarios the Tier-1/2/3 fallback must handle.
type MimePredicate = (mime: string) => boolean

function installMediaRecorderStub(predicate: MimePredicate | null): void {
  if (predicate === null) {
    // Unset the global entirely — Tier-3 fallback branch.
    delete (globalThis as { MediaRecorder?: unknown }).MediaRecorder
    return
  }
  const fake = function () {} as unknown as typeof MediaRecorder
  ;(fake as unknown as { isTypeSupported: (m: string) => boolean }).isTypeSupported = predicate
  ;(globalThis as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder = fake
}

describe('pickRecordingMimeType', () => {
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'MediaRecorder')

  afterEach(() => {
    if (originalDescriptor) {
      Object.defineProperty(globalThis, 'MediaRecorder', originalDescriptor)
    } else {
      delete (globalThis as { MediaRecorder?: unknown }).MediaRecorder
    }
    vi.restoreAllMocks()
  })

  it('returns audio/webm;codecs=opus when supported (Tier 1 — Chrome / Firefox)', () => {
    installMediaRecorderStub((mime) => mime === 'audio/webm;codecs=opus')
    expect(pickRecordingMimeType()).toBe('audio/webm;codecs=opus')
  })

  it('falls back to audio/mp4 when webm is unsupported (Tier 2 — Safari)', () => {
    installMediaRecorderStub((mime) => mime.startsWith('audio/mp4'))
    expect(pickRecordingMimeType()).toBe('audio/mp4')
  })

  it('returns null when no preferred MIME type is supported (Tier 3 — WAV fallback)', () => {
    installMediaRecorderStub(() => false)
    expect(pickRecordingMimeType()).toBeNull()
  })

  it('returns null when MediaRecorder is undefined (Tier 3 — legacy browser)', () => {
    installMediaRecorderStub(null)
    expect(pickRecordingMimeType()).toBeNull()
  })

  it('prefers the first supported option in priority order', () => {
    // Both webm and mp4 are "supported" — priority must still pick webm.
    installMediaRecorderStub(() => true)
    expect(pickRecordingMimeType()).toBe('audio/webm;codecs=opus')
  })

  it('treats an isTypeSupported exception as "not supported" and continues probing', () => {
    installMediaRecorderStub((mime) => {
      if (mime === 'audio/webm;codecs=opus') throw new Error('nope')
      if (mime === 'audio/webm') throw new Error('nope')
      return mime === 'audio/mp4'
    })
    expect(pickRecordingMimeType()).toBe('audio/mp4')
  })
})

describe('extensionForMimeType', () => {
  it('maps webm/opus to webm', () => {
    expect(extensionForMimeType('audio/webm;codecs=opus')).toBe('webm')
  })

  it('maps mp4 variants to m4a', () => {
    expect(extensionForMimeType('audio/mp4')).toBe('m4a')
    expect(extensionForMimeType('audio/mp4;codecs=mp4a.40.2')).toBe('m4a')
  })

  it('maps audio/wav to wav', () => {
    expect(extensionForMimeType('audio/wav')).toBe('wav')
  })
})
