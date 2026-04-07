import { describe, it, expect } from 'vitest'
import { applyArtefactFilters } from '../artefactsFilter'
import type { ArtefactListItem } from '../../../../core/types/artefact'

const make = (over: Partial<ArtefactListItem>): ArtefactListItem => ({
  id: 'id', handle: 'h', title: 't', type: 'code', language: null,
  size_bytes: 0, version: 1, created_at: '', updated_at: '',
  session_id: 's', session_title: 'sess', persona_id: 'p1',
  persona_name: 'P1', persona_monogram: 'P', persona_colour_scheme: 'throat',
  ...over,
})

describe('applyArtefactFilters', () => {
  it('hides nsfw persona artefacts when sanitised', () => {
    const items = [make({ id: 'a', persona_id: 'p1' }), make({ id: 'b', persona_id: 'nsfw' })]
    const out = applyArtefactFilters(items, {
      isSanitised: true, nsfwPersonaIds: new Set(['nsfw']),
      personaFilter: 'all', typeFilter: 'all', search: '',
    })
    expect(out.map((x) => x.id)).toEqual(['a'])
  })

  it('AND-combines whitespace tokens, case insensitive', () => {
    const items = [
      make({ id: 'a', title: 'Snake Game Prototype' }),
      make({ id: 'b', title: 'Snake recipe' }),
      make({ id: 'c', title: 'Game design notes' }),
    ]
    const out = applyArtefactFilters(items, {
      isSanitised: false, nsfwPersonaIds: new Set(),
      personaFilter: 'all', typeFilter: 'all', search: 'snake game',
    })
    expect(out.map((x) => x.id)).toEqual(['a'])
  })

  it('persona and type filters compose with search', () => {
    const items = [
      make({ id: 'a', title: 'foo', persona_id: 'p1', type: 'code' }),
      make({ id: 'b', title: 'foo', persona_id: 'p2', type: 'code' }),
      make({ id: 'c', title: 'foo', persona_id: 'p1', type: 'markdown' }),
    ]
    const out = applyArtefactFilters(items, {
      isSanitised: false, nsfwPersonaIds: new Set(),
      personaFilter: 'p1', typeFilter: 'code', search: 'foo',
    })
    expect(out.map((x) => x.id)).toEqual(['a'])
  })

  it('blank search keeps all', () => {
    const items = [make({ id: 'a' }), make({ id: 'b' })]
    const out = applyArtefactFilters(items, {
      isSanitised: false, nsfwPersonaIds: new Set(),
      personaFilter: 'all', typeFilter: 'all', search: '   ',
    })
    expect(out).toHaveLength(2)
  })
})
