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
//
// `minSpeechFrames` is intentionally identical for medium and high (5):
// short voice commands like "voice off" otherwise slip below the high-
// threshold's 8-frame minimum and never trigger a speech-start. Energy
// sensitivity (positive/negative thresholds) is still strictly monotonic
// across the three presets — that is the parameter the user actually
// wants to tune; minimum-duration is the unimportant one.
export const VAD_PRESETS: Record<VoiceActivationThreshold, VadPreset> = {
  low:    { positiveSpeechThreshold: 0.5,  negativeSpeechThreshold: 0.35, minSpeechFrames: 3 },
  medium: { positiveSpeechThreshold: 0.65, negativeSpeechThreshold: 0.5,  minSpeechFrames: 5 },
  high:   { positiveSpeechThreshold: 0.8,  negativeSpeechThreshold: 0.6,  minSpeechFrames: 5 },
}
