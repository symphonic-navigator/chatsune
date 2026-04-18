import { describe, expect, it } from 'vitest'
import { VAD_PRESETS } from '../vadPresets'
import type { VoiceActivationThreshold } from '../../stores/voiceSettingsStore'

describe('VAD_PRESETS', () => {
  const keys: VoiceActivationThreshold[] = ['low', 'medium', 'high']

  it.each(keys)('exposes four numeric threshold fields for %s', (key) => {
    const preset = VAD_PRESETS[key]
    expect(typeof preset.positiveSpeechThreshold).toBe('number')
    expect(typeof preset.negativeSpeechThreshold).toBe('number')
    expect(typeof preset.minSpeechFrames).toBe('number')
    expect(typeof preset.redemptionFrames).toBe('number')
  })

  it('orders positiveSpeechThreshold so low is the easiest to trigger', () => {
    expect(VAD_PRESETS.low.positiveSpeechThreshold)
      .toBeLessThan(VAD_PRESETS.medium.positiveSpeechThreshold)
    expect(VAD_PRESETS.medium.positiveSpeechThreshold)
      .toBeLessThan(VAD_PRESETS.high.positiveSpeechThreshold)
  })
})
