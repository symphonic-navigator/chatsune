import { useState, useEffect, useMemo } from "react"
import type { EnrichedModelDto } from "../../../core/types/llm"
import { useEnrichedModels } from "../../../core/hooks/useEnrichedModels"
import {
  filterModels,
  sortModels,
  type ModelFilters,
  type ModelSortConfig,
  type SortField,
} from "./modelFilters"

interface ModelBrowserProps {
  onEditConfig?: (model: EnrichedModelDto) => void
  onToggleFavourite?: (model: EnrichedModelDto) => void
  models?: EnrichedModelDto[]
}

const SORT_FIELDS: { field: SortField; label: string }[] = [
  { field: "name", label: "Name" },
  { field: "provider", label: "Provider" },
  { field: "params", label: "Params" },
  { field: "context", label: "Context" },
]

function ratingBadge(model: EnrichedModelDto) {
  const rating = model.curation?.overall_rating ?? "available"
  switch (rating) {
    case "recommended":
      return <span className="text-[10px] text-[#a6e3a1]">Recommended</span>
    case "available":
      return <span className="text-[10px] text-[#89b4fa]">Available</span>
    case "not_recommended":
      return <span className="text-[10px] text-[#f38ba8]">Not Recommended</span>
  }
}

function capabilityIcons(model: EnrichedModelDto) {
  return (
    <div className="flex items-center gap-1.5">
      {model.supports_tool_calls && (
        <span className="text-[10px] font-semibold text-[#a6e3a1]" title="Tool Calls">T</span>
      )}
      {model.supports_vision && (
        <span className="text-[10px] font-semibold text-[#89b4fa]" title="Vision">V</span>
      )}
      {model.supports_reasoning && (
        <span className="text-[10px] font-semibold text-[#f9e2af]" title="Reasoning">R</span>
      )}
    </div>
  )
}

function formatContext(ctx: number): string {
  if (ctx >= 1_000_000) return `${(ctx / 1_000_000).toFixed(1)}M`
  if (ctx >= 1_000) return `${Math.round(ctx / 1_000)}k`
  return String(ctx)
}

function formatParams(model: EnrichedModelDto): string {
  if (!model.parameter_count) return "--"
  if (model.quantisation_level) return `${model.parameter_count} ${model.quantisation_level}`
  return model.parameter_count
}

export function ModelBrowser({
  onEditConfig,
  onToggleFavourite,
  models: externalModels,
}: ModelBrowserProps) {
  const { models: fetchedModels, isLoading: hookLoading, error: hookError } = useEnrichedModels()

  const [filters, setFilters] = useState<ModelFilters>({})
  const [sort, setSort] = useState<ModelSortConfig | null>(null)

  const allModels = externalModels ?? fetchedModels
  const loading = !externalModels && hookLoading
  const error = !externalModels ? hookError : null
  const providerMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const m of allModels) map.set(m.provider_id, m.provider_display_name)
    return map
  }, [allModels])
  const providers = useMemo(
    () => [...providerMap.keys()].sort(),
    [providerMap],
  )

  // Determine if any models are favourited — auto-activate favourites tab
  const hasFavourites = useMemo(
    () => allModels.some((m) => m.user_config?.is_favourite),
    [allModels],
  )

  // Auto-activate favourites filter on first load when user has favourites
  const [initialFavSet, setInitialFavSet] = useState(false)
  useEffect(() => {
    if (!initialFavSet && hasFavourites && allModels.length > 0) {
      setFilters((f) => ({ ...f, favouritesOnly: true }))
      setInitialFavSet(true)
    }
  }, [hasFavourites, allModels.length, initialFavSet])

  // allModels are already filtered (hidden removed) by the hook or parent
  const visibleModels = allModels

  const filtered = useMemo(
    () => filterModels(visibleModels, filters),
    [visibleModels, filters],
  )
  const sorted = useMemo(() => sortModels(filtered, sort), [filtered, sort])

  function handleSort(field: SortField) {
    setSort((prev) => {
      if (prev?.field === field) {
        return prev.direction === "asc"
          ? { field, direction: "desc" }
          : null
      }
      return { field, direction: "asc" }
    })
  }

  function sortIndicator(field: SortField) {
    if (sort?.field !== field) return null
    return sort.direction === "asc" ? " ^" : " v"
  }

  function updateFilter<K extends keyof ModelFilters>(key: K, value: ModelFilters[K]) {
    setFilters((f) => ({ ...f, [key]: value }))
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/6 px-4 py-2.5">
        <div className="text-[12px] text-white/40">
          {visibleModels.length} model{visibleModels.length !== 1 ? "s" : ""}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => updateFilter("favouritesOnly", !filters.favouritesOnly)}
            className={[
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer",
              filters.favouritesOnly
                ? "bg-gold/15 border border-gold/30 text-gold"
                : "border border-white/8 text-white/40 hover:text-white/60 hover:border-white/15",
            ].join(" ")}
          >
            Favourites
          </button>
          <button
            type="button"
            onClick={() => updateFilter("hasCustomisation", !filters.hasCustomisation)}
            className={[
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer",
              filters.hasCustomisation
                ? "bg-[#cba6f7]/15 border border-[#cba6f7]/30 text-[#cba6f7]"
                : "border border-white/8 text-white/40 hover:text-white/60 hover:border-white/15",
            ].join(" ")}
          >
            Customised
          </button>
          <button
            type="button"
            onClick={() => updateFilter("showHidden", !filters.showHidden)}
            className={[
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer",
              filters.showHidden
                ? "bg-[#f38ba8]/15 border border-[#f38ba8]/30 text-[#f38ba8]"
                : "border border-white/8 text-white/40 hover:text-white/60 hover:border-white/15",
            ].join(" ")}
          >
            Hidden
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="border-b border-white/6 px-4 py-2">
        <input
          type="text"
          placeholder="Search models..."
          value={filters.search ?? ""}
          onChange={(e) => updateFilter("search", e.target.value || undefined)}
          className="w-full rounded-lg border border-white/8 bg-elevated px-3 py-1.5 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
        />
      </div>

      {/* Filter row */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/6 px-4 py-2">
        {/* Provider dropdown */}
        <select
          value={filters.provider ?? ""}
          onChange={(e) => updateFilter("provider", e.target.value || undefined)}
          className="rounded-md border border-white/8 bg-elevated px-2 py-1 text-[11px] text-white/60 outline-none focus:border-gold/40 transition-colors cursor-pointer"
        >
          <option value="">All Providers</option>
          {providers.map((p) => (
            <option key={p} value={p}>{providerMap.get(p)}</option>
          ))}
        </select>

        {/* Capability toggles */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => updateFilter("capTools", !filters.capTools)}
            className={[
              "rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors cursor-pointer",
              filters.capTools
                ? "bg-[#a6e3a1]/15 text-[#a6e3a1]"
                : "text-white/30 hover:text-white/50",
            ].join(" ")}
            title="Tool Calls"
          >
            T
          </button>
          <button
            type="button"
            onClick={() => updateFilter("capVision", !filters.capVision)}
            className={[
              "rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors cursor-pointer",
              filters.capVision
                ? "bg-[#89b4fa]/15 text-[#89b4fa]"
                : "text-white/30 hover:text-white/50",
            ].join(" ")}
            title="Vision"
          >
            V
          </button>
          <button
            type="button"
            onClick={() => updateFilter("capReason", !filters.capReason)}
            className={[
              "rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors cursor-pointer",
              filters.capReason
                ? "bg-[#f9e2af]/15 text-[#f9e2af]"
                : "text-white/30 hover:text-white/50",
            ].join(" ")}
            title="Reasoning"
          >
            R
          </button>
        </div>

        {/* Curation dropdown */}
        <select
          value={filters.curation ?? ""}
          onChange={(e) =>
            updateFilter(
              "curation",
              (e.target.value as ModelFilters["curation"]) || undefined,
            )
          }
          className="rounded-md border border-white/8 bg-elevated px-2 py-1 text-[11px] text-white/60 outline-none focus:border-gold/40 transition-colors cursor-pointer"
        >
          <option value="">All Ratings</option>
          <option value="recommended">Recommended</option>
          <option value="available">Available</option>
          <option value="not_recommended">Not Recommended</option>
        </select>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem] items-center gap-1 border-b border-white/6 px-4 py-1.5 text-[10px] font-medium uppercase tracking-wider text-white/30">
        <span title="Favourite">Fav</span>
        {SORT_FIELDS.map((sf) => (
          <button
            key={sf.field}
            type="button"
            onClick={() => handleSort(sf.field)}
            className="cursor-pointer text-left hover:text-white/50 transition-colors"
          >
            {sf.label}{sortIndicator(sf.field)}
          </button>
        ))}
        <span>Caps</span>
        <span>Rating</span>
      </div>

      {/* Model list */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center py-12 text-[12px] text-white/30">
            Loading models...
          </div>
        )}

        {error && (
          <div className="mx-4 mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-400">
            {error}
          </div>
        )}

        {!loading && !error && sorted.length === 0 && (
          <div className="flex items-center justify-center py-12 text-[12px] text-white/30">
            No models match the current filters
          </div>
        )}

        {sorted.map((model) => {
          const isFav = model.user_config?.is_favourite ?? false
          const hasConfig = model.user_config != null && (
            model.user_config.is_favourite ||
            model.user_config.is_hidden ||
            model.user_config.custom_display_name != null ||
            model.user_config.custom_context_window != null ||
            (model.user_config.notes != null && model.user_config.notes.length > 0) ||
            (model.user_config.system_prompt_addition != null && model.user_config.system_prompt_addition.length > 0)
          )

          return (
            <div
              key={model.unique_id}
              onClick={() => onEditConfig?.(model)}
              className={[
                "grid grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem] items-center gap-1 border-b border-white/6 px-4 py-2 text-[12px] transition-colors",
                "cursor-pointer hover:bg-white/4",
                model.user_config?.is_hidden ? "opacity-45" : "",
              ].join(" ")}
            >
              {/* Favourite star */}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleFavourite?.(model)
                }}
                className={[
                  "text-[13px] transition-colors cursor-pointer",
                  isFav ? "text-gold" : "text-white/15 hover:text-white/30",
                ].join(" ")}
                title={isFav ? "Remove from favourites" : "Add to favourites"}
              >
                {isFav ? "\u2605" : "\u2606"}
              </button>

              {/* Name + customisation indicator */}
              <div className="min-w-0 flex items-center gap-1.5">
                <span className="truncate text-[12px] text-white/80">
                  {model.user_config?.custom_display_name ?? model.display_name}
                </span>
                {hasConfig && (
                  <span className="text-[10px] text-[#cba6f7] flex-shrink-0" title="Customised">&#9670;</span>
                )}
                {model.user_config?.custom_display_name && (
                  <span className="truncate text-[9px] text-white/25 italic flex-shrink-0">
                    {model.display_name}
                  </span>
                )}
                {model.user_config?.is_hidden && (
                  <span className="text-[9px] text-white/30 flex-shrink-0">HIDDEN</span>
                )}
              </div>

              {/* Provider */}
              <span className="truncate text-[11px] text-white/40">{model.provider_display_name}</span>

              {/* Params */}
              <span className="text-[11px] text-white/55">
                {model.parameter_count ? (
                  <>
                    {model.parameter_count}
                    {model.quantisation_level && (
                      <span className="ml-1 text-[9px] text-white/25">{model.quantisation_level}</span>
                    )}
                  </>
                ) : (
                  <span className="text-white/20">--</span>
                )}
              </span>

              {/* Context */}
              <span className="text-[11px] text-white/40">{formatContext(model.context_window)}</span>

              {/* Capabilities */}
              {capabilityIcons(model)}

              {/* Rating */}
              {ratingBadge(model)}
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="border-t border-white/6 px-4 py-2 text-[11px] text-white/30">
        {sorted.length} of {visibleModels.length} shown
      </div>
    </div>
  )
}
