import type { VoiceActivationThreshold } from '../stores/voiceSettingsStore'

export interface VadPreset {
  positiveSpeechThreshold: number
  negativeSpeechThreshold: number
  minSpeechFrames: number
}

// Preset table is expressed in frames (matching Silero's native units).
// `minSpeechFrames` is converted to `minSpeechMs` in audioCapture.ts where
// it is handed to MicVAD.new. Redemption (silence-tolerance) is configured
// per user via voiceSettingsStore.redemptionMs and is no longer part of
// the threshold preset.
export const VAD_PRESETS: Record<VoiceActivationThreshold, VadPreset> = {
  low:    { positiveSpeechThreshold: 0.5,  negativeSpeechThreshold: 0.35, minSpeechFrames: 3 },
  medium: { positiveSpeechThreshold: 0.65, negativeSpeechThreshold: 0.5,  minSpeechFrames: 5 },
  high:   { positiveSpeechThreshold: 0.8,  negativeSpeechThreshold: 0.6,  minSpeechFrames: 8 },
}
