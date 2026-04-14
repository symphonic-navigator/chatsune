// TODO Phase 9: reinstate filter/sort/search helpers once the new
// connections/models pipeline is in place. All helpers are identity /
// pass-through placeholders for now.

import type { EnrichedModelDto } from "../../../core/types/llm"

export interface ModelFilters {
  search?: string
  provider?: string
  capTools?: boolean
  capVision?: boolean
  capReason?: boolean
  favouritesOnly?: boolean
  hasCustomisation?: boolean
  showHidden?: boolean
}

export type SortField = "name" | "provider" | "context" | "params" | "rating"

export interface ModelSortConfig {
  field: SortField
  direction: "asc" | "desc"
}

export function slugWithoutProvider(uniqueId: string): string {
  const idx = uniqueId.indexOf(":")
  return idx >= 0 ? uniqueId.slice(idx + 1) : uniqueId
}

export function matchesSearch(_model: EnrichedModelDto, _query: string): boolean {
  return true
}

export function filterModels(
  models: EnrichedModelDto[],
  _filters: ModelFilters,
): EnrichedModelDto[] {
  return models
}

export function sortModels(
  models: EnrichedModelDto[],
  _config: ModelSortConfig | null,
): EnrichedModelDto[] {
  return models
}
