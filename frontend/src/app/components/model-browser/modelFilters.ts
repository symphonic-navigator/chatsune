import type { EnrichedModelDto, ModelRating } from "../../../core/types/llm"

export interface ModelFilters {
  search?: string
  provider?: string
  capTools?: boolean
  capVision?: boolean
  capReason?: boolean
  curation?: "recommended" | "available" | "not_recommended"
  favouritesOnly?: boolean
  hasCustomisation?: boolean
  showHidden?: boolean
}

export type SortField = "name" | "provider" | "context" | "params" | "rating"

export interface ModelSortConfig {
  field: SortField
  direction: "asc" | "desc"
}

/** Extract the model slug from a unique_id (everything after the first colon). */
export function slugWithoutProvider(uniqueId: string): string {
  const idx = uniqueId.indexOf(":")
  return idx >= 0 ? uniqueId.slice(idx + 1) : uniqueId
}

/** Check whether a model matches a free-text search query. */
export function matchesSearch(model: EnrichedModelDto, query: string): boolean {
  const q = query.toLowerCase().trim()
  if (!q) return true
  return (
    model.display_name.toLowerCase().includes(q) ||
    model.model_id.toLowerCase().includes(q) ||
    (model.user_config?.custom_display_name?.toLowerCase().includes(q) ?? false)
  )
}

/** Apply all active filters to a model list. */
export function filterModels(
  models: EnrichedModelDto[],
  filters: ModelFilters,
): EnrichedModelDto[] {
  return models.filter((m) => {
    // Hidden filter: by default exclude user-hidden models; when active show ONLY hidden
    if (filters.showHidden) {
      if (!m.user_config?.is_hidden) return false
    } else {
      if (m.user_config?.is_hidden) return false
    }

    if (filters.search && !matchesSearch(m, filters.search)) return false

    if (filters.provider && m.provider_id !== filters.provider) return false

    if (filters.capTools && !m.supports_tool_calls) return false
    if (filters.capVision && !m.supports_vision) return false
    if (filters.capReason && !m.supports_reasoning) return false

    if (filters.curation) {
      const rating = m.curation?.overall_rating ?? null
      switch (filters.curation) {
        case "recommended":
          if (rating !== "recommended") return false
          break
        case "not_recommended":
          if (rating !== "not_recommended") return false
          break
        case "available":
          // "available" includes recommended, available, and uncurated
          if (rating === "not_recommended") return false
          break
      }
    }

    if (filters.favouritesOnly && !m.user_config?.is_favourite) return false

    if (filters.hasCustomisation) {
      const cfg = m.user_config
      if (!cfg) return false
      const hasCustom =
        cfg.is_favourite ||
        cfg.is_hidden ||
        cfg.custom_display_name != null ||
        cfg.custom_context_window != null ||
        (cfg.notes != null && cfg.notes.length > 0) ||
        (cfg.system_prompt_addition != null && cfg.system_prompt_addition.length > 0)
      if (!hasCustom) return false
    }

    return true
  })
}

/** Parse the numeric portion of a parameter_count string (e.g. "70B" -> 70). */
function parseParamCount(paramStr: string | null): number | null {
  if (!paramStr) return null
  const match = paramStr.match(/^([\d.]+)/)
  return match ? parseFloat(match[1]) : null
}

const RATING_ORDER: Record<ModelRating, number> = {
  recommended: 0,
  available: 1,
  not_recommended: 2,
}

/** Sort models by the given configuration. Null config returns the list unchanged. */
export function sortModels(
  models: EnrichedModelDto[],
  config: ModelSortConfig | null,
): EnrichedModelDto[] {
  if (!config) return models

  const sorted = [...models]
  const dir = config.direction === "asc" ? 1 : -1

  sorted.sort((a, b) => {
    let cmp = 0
    switch (config.field) {
      case "name":
        cmp = a.display_name.localeCompare(b.display_name)
        break
      case "provider":
        cmp = a.provider_id.localeCompare(b.provider_id)
        break
      case "context":
        cmp = a.context_window - b.context_window
        break
      case "params": {
        const pa = parseParamCount(a.parameter_count)
        const pb = parseParamCount(b.parameter_count)
        if (pa === null && pb === null) cmp = 0
        else if (pa === null) cmp = 1 // null sorts last regardless of direction
        else if (pb === null) cmp = -1
        else cmp = pa - pb
        break
      }
      case "rating": {
        const ra = a.curation ? RATING_ORDER[a.curation.overall_rating] : 3
        const rb = b.curation ? RATING_ORDER[b.curation.overall_rating] : 3
        cmp = ra - rb
        break
      }
    }
    return cmp * dir
  })

  return sorted
}
