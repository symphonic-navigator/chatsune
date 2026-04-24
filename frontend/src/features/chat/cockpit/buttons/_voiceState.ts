export type VoiceUIState =
  | { kind: 'normal-off' }
  | { kind: 'normal-on' }
  | { kind: 'normal-playing' }
  | { kind: 'live-mic-on' }
  | { kind: 'live-mic-muted' }
  | { kind: 'live-playing' }
  | { kind: 'disabled' }

export function deriveVoiceUIState({
  personaHasVoice,
  liveMode,
  ttsPlaying,
  autoRead,
  micMuted,
}: {
  personaHasVoice: boolean
  liveMode: boolean
  ttsPlaying: boolean
  autoRead: boolean
  micMuted: boolean
}): VoiceUIState {
  if (!personaHasVoice) return { kind: 'disabled' }
  if (liveMode) {
    if (ttsPlaying) return { kind: 'live-playing' }
    return micMuted ? { kind: 'live-mic-muted' } : { kind: 'live-mic-on' }
  }
  if (ttsPlaying) return { kind: 'normal-playing' }
  return autoRead ? { kind: 'normal-on' } : { kind: 'normal-off' }
}
