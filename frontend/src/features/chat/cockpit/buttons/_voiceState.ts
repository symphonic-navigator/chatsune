import type { VoiceLifecycle } from '@/features/voice-commands'

export type VoiceUIState =
  | { kind: 'normal-off' }
  | { kind: 'normal-on' }
  | { kind: 'normal-playing' }
  | { kind: 'live-mic-on' }
  | { kind: 'live-mic-muted' }
  | { kind: 'live-playing' }
  | { kind: 'live-paused' }
  | { kind: 'disabled' }

export function deriveVoiceUIState({
  personaHasVoice,
  liveMode,
  ttsPlaying,
  autoRead,
  micMuted,
  lifecycle,
}: {
  personaHasVoice: boolean
  liveMode: boolean
  ttsPlaying: boolean
  autoRead: boolean
  micMuted: boolean
  lifecycle: VoiceLifecycle
}): VoiceUIState {
  if (!personaHasVoice) return { kind: 'disabled' }
  if (liveMode) {
    if (ttsPlaying) return { kind: 'live-playing' }
    // Paused takes precedence over the mic on/muted pair: in paused mode the
    // assistant ignores incoming audio (only Vosk listens for the resume cue),
    // so the mute toggle is irrelevant. The button's click resumes instead.
    if (lifecycle === 'paused') return { kind: 'live-paused' }
    return micMuted ? { kind: 'live-mic-muted' } : { kind: 'live-mic-on' }
  }
  if (ttsPlaying) return { kind: 'normal-playing' }
  return autoRead ? { kind: 'normal-on' } : { kind: 'normal-off' }
}
