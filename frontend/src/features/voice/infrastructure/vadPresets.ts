import type { VoiceActivationThreshold } from '../stores/voiceSettingsStore'

export interface VadPreset {
  positiveSpeechThreshold: number
  negativeSpeechThreshold: number
  minSpeechFrames: number
  redemptionFrames: number
}

// Preset table is expressed in frames (matching Silero's native units) for
// readability. The vad-web public API takes these two values as `minSpeechMs`
// and `redemptionMs`; conversion lives in audioCapture.ts where the options
// are actually handed to MicVAD.new.
export const VAD_PRESETS: Record<VoiceActivationThreshold, VadPreset> = {
  low: {
    positiveSpeechThreshold: 0.5,
    negativeSpeechThreshold: 0.35,
    minSpeechFrames: 3,
    redemptionFrames: 8,
  },
  medium: {
    positiveSpeechThreshold: 0.65,
    negativeSpeechThreshold: 0.5,
    minSpeechFrames: 5,
    redemptionFrames: 10,
  },
  high: {
    positiveSpeechThreshold: 0.8,
    negativeSpeechThreshold: 0.6,
    minSpeechFrames: 8,
    redemptionFrames: 12,
  },
}
