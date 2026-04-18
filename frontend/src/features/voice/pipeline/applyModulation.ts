import type { SpeechSegment } from '../types'

export interface VoiceModulation {
  dialogue_speed: number
  dialogue_pitch: number
  narrator_speed: number
  narrator_pitch: number
}

export const NEUTRAL_MODULATION: VoiceModulation = {
  dialogue_speed: 1.0,
  dialogue_pitch: 0,
  narrator_speed: 1.0,
  narrator_pitch: 0,
}

/**
 * Resolve modulation from a persona's voice_config, falling back to neutral
 * values for any missing fields. Accepts undefined/null gracefully so callers
 * can chain `persona?.voice_config` without extra guards.
 */
export function resolveModulation(
  voiceConfig: {
    dialogue_speed?: number
    dialogue_pitch?: number
    narrator_speed?: number
    narrator_pitch?: number
  } | null | undefined,
): VoiceModulation {
  return {
    dialogue_speed: voiceConfig?.dialogue_speed ?? 1.0,
    dialogue_pitch: voiceConfig?.dialogue_pitch ?? 0,
    narrator_speed: voiceConfig?.narrator_speed ?? 1.0,
    narrator_pitch: voiceConfig?.narrator_pitch ?? 0,
  }
}

/**
 * Decorate a SpeechSegment with the correct speed/pitch for its type
 * (voice → dialogue_*, narration → narrator_*). Returns the original
 * segment unchanged if the resolved values are neutral, to avoid a
 * pointless allocation and to make downstream `needsModulation` checks cheap.
 */
export function applyModulation(
  segment: SpeechSegment,
  modulation: VoiceModulation,
): SpeechSegment {
  const speed = segment.type === 'voice' ? modulation.dialogue_speed : modulation.narrator_speed
  const pitch = segment.type === 'voice' ? modulation.dialogue_pitch : modulation.narrator_pitch
  if (speed === 1.0 && pitch === 0) return segment
  return { ...segment, speed, pitch }
}
