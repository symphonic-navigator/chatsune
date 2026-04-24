import type { EnrichedModelDto } from '../../../core/types/llm'

export type BillingFilter =
  | 'all'
  | 'no_per_token'
  | 'free'
  | 'subscription'
  | 'pay_per_token'

export interface ModelFilters {
  search?: string
  favouritesOnly?: boolean
  capTools?: boolean
  capVision?: boolean
  capReason?: boolean
  showHidden?: boolean
  billing?: BillingFilter
}

export type SortField = 'name' | 'context' | 'params'

export interface ModelSortConfig {
  field: SortField
  direction: 'asc' | 'desc'
}

export function slugWithoutConnection(uniqueId: string): string {
  const idx = uniqueId.indexOf(':')
  return idx >= 0 ? uniqueId.slice(idx + 1) : uniqueId
}

export function matchesSearch(model: EnrichedModelDto, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  const display = (model.user_config?.custom_display_name ?? model.display_name).toLowerCase()
  return (
    display.includes(q) ||
    model.model_id.toLowerCase().includes(q) ||
    model.unique_id.toLowerCase().includes(q)
  )
}

export function applyModelFilters(
  models: EnrichedModelDto[],
  filters: ModelFilters,
): EnrichedModelDto[] {
  return models.filter((m) => {
    if (filters.favouritesOnly && !m.user_config?.is_favourite) return false
    if (!filters.showHidden && m.user_config?.is_hidden) return false
    if (filters.capTools && !m.supports_tool_calls) return false
    if (filters.capVision && !m.supports_vision) return false
    if (filters.capReason && !m.supports_reasoning) return false
    if (filters.billing && filters.billing !== 'all') {
      const cat = m.billing_category ?? null
      if (cat === null) return false
      switch (filters.billing) {
        case 'no_per_token':
          if (cat !== 'free' && cat !== 'subscription') return false
          break
        case 'free':
          if (cat !== 'free') return false
          break
        case 'subscription':
          if (cat !== 'subscription') return false
          break
        case 'pay_per_token':
          if (cat !== 'pay_per_token') return false
          break
      }
    }
    if (filters.search && !matchesSearch(m, filters.search)) return false
    return true
  })
}

export function sortModels(
  models: EnrichedModelDto[],
  config: ModelSortConfig | null,
): EnrichedModelDto[] {
  if (!config) return models
  const dir = config.direction === 'asc' ? 1 : -1
  return [...models].sort((a, b) => {
    switch (config.field) {
      case 'name': {
        const an = a.user_config?.custom_display_name ?? a.display_name
        const bn = b.user_config?.custom_display_name ?? b.display_name
        return an.localeCompare(bn) * dir
      }
      case 'context': {
        const ac = a.user_config?.custom_context_window ?? a.context_window
        const bc = b.user_config?.custom_context_window ?? b.context_window
        return (ac - bc) * dir
      }
      case 'params': {
        const ap = a.raw_parameter_count ?? 0
        const bp = b.raw_parameter_count ?? 0
        return (ap - bp) * dir
      }
      default:
        return 0
    }
  })
}

// Kept for backward compatibility; identical to applyModelFilters.
export const filterModels = applyModelFilters
