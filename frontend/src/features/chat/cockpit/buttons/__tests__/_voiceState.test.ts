import { describe, it, expect } from 'vitest'
import { deriveVoiceUIState } from '../_voiceState'
import type { VoiceLifecycle } from '@/features/voice-commands'

describe('deriveVoiceUIState', () => {
  const base = {
    personaHasVoice: true,
    liveMode: false,
    ttsPlaying: false,
    autoRead: false,
    micMuted: false,
    lifecycle: 'active' as VoiceLifecycle,
  }

  it('disabled when persona has no voice', () => {
    expect(deriveVoiceUIState({ ...base, personaHasVoice: false }))
      .toEqual({ kind: 'disabled' })
  })

  it('normal off', () => {
    expect(deriveVoiceUIState(base)).toEqual({ kind: 'normal-off' })
  })

  it('normal on', () => {
    expect(deriveVoiceUIState({ ...base, autoRead: true }))
      .toEqual({ kind: 'normal-on' })
  })

  it('normal playing', () => {
    expect(deriveVoiceUIState({ ...base, ttsPlaying: true }))
      .toEqual({ kind: 'normal-playing' })
  })

  it('live mic on', () => {
    expect(deriveVoiceUIState({ ...base, liveMode: true }))
      .toEqual({ kind: 'live-mic-on' })
  })

  it('live mic muted', () => {
    expect(deriveVoiceUIState({ ...base, liveMode: true, micMuted: true }))
      .toEqual({ kind: 'live-mic-muted' })
  })

  it('live playing — mic state does not influence', () => {
    expect(deriveVoiceUIState({
      ...base, liveMode: true, ttsPlaying: true, micMuted: true,
    })).toEqual({ kind: 'live-playing' })
  })
})

describe('live-paused state', () => {
  const baseInput = {
    personaHasVoice: true,
    liveMode: true,
    ttsPlaying: false,
    autoRead: false,
    micMuted: false,
    lifecycle: 'paused' as VoiceLifecycle,
  }

  it('returns live-paused when live and paused', () => {
    expect(deriveVoiceUIState(baseInput).kind).toBe('live-paused')
  })

  it('takes precedence over mic-on', () => {
    expect(deriveVoiceUIState({ ...baseInput, micMuted: false }).kind).toBe('live-paused')
  })

  it('takes precedence over mic-muted', () => {
    expect(deriveVoiceUIState({ ...baseInput, micMuted: true }).kind).toBe('live-paused')
  })

  it('does NOT trigger when not in live mode', () => {
    const r = deriveVoiceUIState({ ...baseInput, liveMode: false })
    expect(r.kind).not.toBe('live-paused')
  })

  it('does NOT trigger when lifecycle is active', () => {
    const r = deriveVoiceUIState({ ...baseInput, lifecycle: 'active' })
    expect(r.kind).not.toBe('live-paused')
  })

  it('live-playing wins over live-paused (TTS interrupt is the most urgent action)', () => {
    expect(deriveVoiceUIState({ ...baseInput, ttsPlaying: true }).kind).toBe('live-playing')
  })
})
