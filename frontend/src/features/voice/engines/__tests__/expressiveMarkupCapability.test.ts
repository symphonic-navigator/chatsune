import { describe, it, expect } from 'vitest'
import { providerSupportsExpressiveMarkup } from '../expressiveMarkupCapability'

const defs = [
  { id: 'mistral_voice', capabilities: ['tts_provider', 'stt_provider'] },
  { id: 'xai_voice', capabilities: ['tts_provider', 'stt_provider', 'tts_expressive_markup'] },
]

describe('providerSupportsExpressiveMarkup', () => {
  it('returns true when the integration advertises the capability', () => {
    expect(providerSupportsExpressiveMarkup('xai_voice', defs)).toBe(true)
  })

  it('returns false when the integration does not', () => {
    expect(providerSupportsExpressiveMarkup('mistral_voice', defs)).toBe(false)
  })

  it('returns false when the integration is unknown', () => {
    expect(providerSupportsExpressiveMarkup('ghost', defs)).toBe(false)
  })

  it('returns false for empty / null input', () => {
    expect(providerSupportsExpressiveMarkup(null, defs)).toBe(false)
    expect(providerSupportsExpressiveMarkup('', defs)).toBe(false)
    expect(providerSupportsExpressiveMarkup('xai_voice', [])).toBe(false)
  })
})
