import type { VoicePreset } from '../../../voice/types'

// Populated at runtime by the plugin from the Mistral voices list.
// Empty at module load; engines.ts reads via this mutable export.
export const mistralVoices: { current: VoicePreset[] } = { current: [] }
