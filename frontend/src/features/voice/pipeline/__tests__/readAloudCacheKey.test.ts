import { describe, expect, it } from 'vitest'
import { readAloudCacheKey } from '../readAloudCacheKey'

describe('readAloudCacheKey', () => {
  it('joins all four components with colons', () => {
    expect(readAloudCacheKey('msg-1', 'voice-a', 'narr-b', 'play')).toBe('msg-1:voice-a:narr-b:play')
  })
  it('renders null narrator voice as a dash', () => {
    expect(readAloudCacheKey('msg-1', 'voice-a', null, 'off')).toBe('msg-1:voice-a:-:off')
  })
  it('differs when the primary voice changes', () => {
    expect(readAloudCacheKey('m', 'v1', null, 'off')).not.toBe(readAloudCacheKey('m', 'v2', null, 'off'))
  })
  it('differs when the mode changes', () => {
    expect(readAloudCacheKey('m', 'v', null, 'off')).not.toBe(readAloudCacheKey('m', 'v', null, 'play'))
  })
})
