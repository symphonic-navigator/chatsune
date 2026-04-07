import type { ArtefactListItem, ArtefactType } from '../../../core/types/artefact'

export interface ArtefactFilterState {
  isSanitised: boolean
  nsfwPersonaIds: Set<string>
  personaFilter: string
  typeFilter: ArtefactType | 'all'
  search: string
}

export function applyArtefactFilters(
  items: ArtefactListItem[],
  state: ArtefactFilterState,
): ArtefactListItem[] {
  let result = items

  if (state.isSanitised) {
    result = result.filter((a) => !state.nsfwPersonaIds.has(a.persona_id))
  }

  if (state.personaFilter !== 'all') {
    result = result.filter((a) => a.persona_id === state.personaFilter)
  }

  if (state.typeFilter !== 'all') {
    result = result.filter((a) => a.type === state.typeFilter)
  }

  const tokens = state.search.toLowerCase().split(/\s+/).filter(Boolean)
  if (tokens.length > 0) {
    result = result.filter((a) => {
      const title = a.title.toLowerCase()
      return tokens.every((t) => title.includes(t))
    })
  }

  return result
}
