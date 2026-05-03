import { describe, it, expect } from 'vitest'
import { sortPersonas } from './personaSort'
import type { PersonaDto } from '../../../core/types/persona'

function persona(
  id: string,
  overrides: Partial<PersonaDto> = {},
): PersonaDto {
  return {
    id,
    user_id: 'u',
    name: id,
    tagline: '',
    model_unique_id: null,
    system_prompt: '',
    temperature: 0.8,
    reasoning_enabled: false,
    soft_cot_enabled: false,
    vision_fallback_model: null,
    nsfw: false,
    use_memory: true,
    colour_scheme: 'solar',
    display_order: 0,
    monogram: id.slice(0, 1).toUpperCase(),
    pinned: false,
    profile_image: null,
    profile_crop: null,
    mcp_config: null,
    integrations_config: null,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('sortPersonas', () => {
  it('places pinned personas before unpinned regardless of LRU', () => {
    const list = [
      persona('a', { pinned: false, last_used_at: '2025-12-01T00:00:00Z' }),
      persona('b', { pinned: true, last_used_at: '2025-01-01T00:00:00Z' }),
    ]
    const out = sortPersonas(list)
    expect(out.map((p) => p.id)).toEqual(['b', 'a'])
  })

  it('orders within pinned by last_used_at descending', () => {
    const list = [
      persona('old', { pinned: true, last_used_at: '2025-01-01T00:00:00Z' }),
      persona('new', { pinned: true, last_used_at: '2025-06-01T00:00:00Z' }),
    ]
    const out = sortPersonas(list)
    expect(out.map((p) => p.id)).toEqual(['new', 'old'])
  })

  it('orders within unpinned by last_used_at descending', () => {
    const list = [
      persona('older', { last_used_at: '2025-01-01T00:00:00Z' }),
      persona('newer', { last_used_at: '2025-06-01T00:00:00Z' }),
    ]
    const out = sortPersonas(list)
    expect(out.map((p) => p.id)).toEqual(['newer', 'older'])
  })

  it('falls back to created_at descending when last_used_at missing', () => {
    const list = [
      persona('older', { created_at: '2025-01-01T00:00:00Z' }),
      persona('newer', { created_at: '2025-06-01T00:00:00Z' }),
    ]
    const out = sortPersonas(list)
    expect(out.map((p) => p.id)).toEqual(['newer', 'older'])
  })

  it('places brand-new personas (no last_used_at) above older-used ones', () => {
    const list = [
      persona('used', {
        last_used_at: '2025-01-01T00:00:00Z',
        created_at: '2024-01-01T00:00:00Z',
      }),
      persona('brandnew', {
        last_used_at: null,
        created_at: '2025-12-31T00:00:00Z',
      }),
    ]
    const out = sortPersonas(list)
    expect(out.map((p) => p.id)).toEqual(['brandnew', 'used'])
  })
})
