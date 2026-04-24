import { describe, it, expect } from 'vitest'
import { deriveVoiceUIState } from '../_voiceState'

describe('deriveVoiceUIState', () => {
  const base = {
    personaHasVoice: true,
    liveMode: false,
    ttsPlaying: false,
    autoRead: false,
    micMuted: false,
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
