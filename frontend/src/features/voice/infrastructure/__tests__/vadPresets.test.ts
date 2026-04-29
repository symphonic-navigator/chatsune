import { describe, it, expect } from 'vitest'
import { VAD_PRESETS } from '../vadPresets'

describe('VAD_PRESETS', () => {
  it('exposes positive/negative/minSpeech for each threshold', () => {
    for (const key of ['low', 'medium', 'high'] as const) {
      const preset = VAD_PRESETS[key]
      expect(typeof preset.positiveSpeechThreshold).toBe('number')
      expect(typeof preset.negativeSpeechThreshold).toBe('number')
      expect(typeof preset.minSpeechFrames).toBe('number')
      expect(preset).not.toHaveProperty('redemptionFrames')
    }
  })

  it('thresholds are monotonically increasing low → medium → high', () => {
    expect(VAD_PRESETS.low.positiveSpeechThreshold)
      .toBeLessThan(VAD_PRESETS.medium.positiveSpeechThreshold)
    expect(VAD_PRESETS.medium.positiveSpeechThreshold)
      .toBeLessThan(VAD_PRESETS.high.positiveSpeechThreshold)
  })
})
