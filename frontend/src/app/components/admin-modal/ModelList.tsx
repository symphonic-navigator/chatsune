import { useState, useMemo } from "react"
import type { ModelMetaDto, ModelRating } from "../../../core/types/llm"

interface ModelListProps {
  models: ModelMetaDto[]
  onSelectModel: (model: ModelMetaDto) => void
}

type SortField = "provider" | "name" | "context" | "params"
type SortDir = "asc" | "desc"
type RatingFilter = "all" | ModelRating | "none"
type VisibilityFilter = "all" | "visible" | "hidden"


/** Format context window nicely */
function formatContext(ctx: number): string {
  if (ctx >= 1_000_000) return `${(ctx / 1_000_000).toFixed(1)}M`
  if (ctx >= 1_000) return `${Math.round(ctx / 1_000)}k`
  return String(ctx)
}

const RATING_COLOURS: Record<ModelRating, string> = {
  recommended: "text-[#a6e3a1] bg-[#a6e3a1]/10 border-[#a6e3a1]/25",
  available: "text-[#89b4fa] bg-[#89b4fa]/10 border-[#89b4fa]/25",
  not_recommended: "text-[#f38ba8] bg-[#f38ba8]/10 border-[#f38ba8]/25",
}

const RATING_LABELS: Record<ModelRating, string> = {
  recommended: "Rec",
  available: "Avail",
  not_recommended: "Not Rec",
}

export function ModelList({ models, onSelectModel }: ModelListProps) {
  const [search, setSearch] = useState("")
  const [providerFilter, setProviderFilter] = useState<string>("all")
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>("all")
  const [visibilityFilter, setVisibilityFilter] = useState<VisibilityFilter>("all")
  const [capTools, setCapTools] = useState(false)
  const [capVision, setCapVision] = useState(false)
  const [capReasoning, setCapReasoning] = useState(false)
  const [ctxMin, setCtxMin] = useState("")
  const [ctxMax, setCtxMax] = useState("")
  const [sortField, setSortField] = useState<SortField>("name")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  // Unique providers for the dropdown
  const providerMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const m of models) map.set(m.provider_id, m.provider_display_name)
    return map
  }, [models])
  const providers = useMemo(
    () => [...providerMap.keys()].sort(),
    [providerMap],
  )

  // Filtering
  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    const minCtx = ctxMin ? parseInt(ctxMin, 10) * 1024 : 0
    const maxCtx = ctxMax ? parseInt(ctxMax, 10) * 1024 : Infinity

    return models.filter((m) => {
      // Text search
      if (q && !m.display_name.toLowerCase().includes(q) && !m.model_id.toLowerCase().includes(q)) {
        return false
      }
      // Provider
      if (providerFilter !== "all" && m.provider_id !== providerFilter) return false
      // Rating
      if (ratingFilter === "none" && m.curation !== null) return false
      if (ratingFilter !== "all" && ratingFilter !== "none" && m.curation?.overall_rating !== ratingFilter) return false
      // Visibility
      if (visibilityFilter === "hidden" && !m.curation?.hidden) return false
      if (visibilityFilter === "visible" && m.curation?.hidden) return false
      // Capabilities
      if (capTools && !m.supports_tool_calls) return false
      if (capVision && !m.supports_vision) return false
      if (capReasoning && !m.supports_reasoning) return false
      // Context range
      if (m.context_window < minCtx) return false
      if (m.context_window > maxCtx) return false

      return true
    })
  }, [models, search, providerFilter, ratingFilter, visibilityFilter, capTools, capVision, capReasoning, ctxMin, ctxMax])

  // Sorting
  const sorted = useMemo(() => {
    const list = [...filtered]
    const dir = sortDir === "asc" ? 1 : -1

    list.sort((a, b) => {
      switch (sortField) {
        case "provider":
          return dir * a.provider_id.localeCompare(b.provider_id)
        case "name":
          return dir * a.display_name.localeCompare(b.display_name)
        case "context":
          return dir * (a.context_window - b.context_window)
        case "params":
          return dir * ((a.raw_parameter_count ?? 0) - (b.raw_parameter_count ?? 0))
        default:
          return 0
      }
    })

    return list
  }, [filtered, sortField, sortDir])

  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDir("asc")
    }
  }

  function sortIndicator(field: SortField) {
    if (sortField !== field) return ""
    return sortDir === "asc" ? " \u25B2" : " \u25BC"
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Filters bar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/6 px-4 py-2.5">
        {/* Search */}
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search models"
          placeholder="Search models..."
          className="w-48 rounded-lg border border-white/8 bg-elevated px-3 py-1.5 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
        />

        {/* Provider */}
        <select
          value={providerFilter}
          onChange={(e) => setProviderFilter(e.target.value)}
          aria-label="Filter by provider"
          className="rounded-lg border border-white/8 bg-elevated px-2 py-1.5 text-[11px] text-white/70 outline-none focus:border-gold/40 transition-colors cursor-pointer"
        >
          <option value="all">All Providers</option>
          {providers.map((p) => (
            <option key={p} value={p}>{providerMap.get(p)}</option>
          ))}
        </select>

        {/* Capability toggles */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setCapTools((v) => !v)}
            aria-label="Filter: tool calls"
            aria-pressed={capTools}
            title="Tool Calls"
            className={[
              "rounded px-1.5 py-1 text-[10px] font-bold transition-colors cursor-pointer border",
              capTools
                ? "text-[#a6e3a1] bg-[#a6e3a1]/15 border-[#a6e3a1]/30"
                : "text-white/60 border-white/8 hover:text-white/80 hover:border-white/15",
            ].join(" ")}
          >
            T
          </button>
          <button
            type="button"
            onClick={() => setCapVision((v) => !v)}
            aria-label="Filter: vision"
            aria-pressed={capVision}
            title="Vision"
            className={[
              "rounded px-1.5 py-1 text-[10px] font-bold transition-colors cursor-pointer border",
              capVision
                ? "text-[#89b4fa] bg-[#89b4fa]/15 border-[#89b4fa]/30"
                : "text-white/60 border-white/8 hover:text-white/80 hover:border-white/15",
            ].join(" ")}
          >
            V
          </button>
          <button
            type="button"
            onClick={() => setCapReasoning((v) => !v)}
            aria-label="Filter: reasoning"
            aria-pressed={capReasoning}
            title="Reasoning"
            className={[
              "rounded px-1.5 py-1 text-[10px] font-bold transition-colors cursor-pointer border",
              capReasoning
                ? "text-[#f9e2af] bg-[#f9e2af]/15 border-[#f9e2af]/30"
                : "text-white/60 border-white/8 hover:text-white/80 hover:border-white/15",
            ].join(" ")}
          >
            R
          </button>
        </div>

        {/* Rating filter */}
        <select
          value={ratingFilter}
          onChange={(e) => setRatingFilter(e.target.value as RatingFilter)}
          aria-label="Filter by rating"
          className="rounded-lg border border-white/8 bg-elevated px-2 py-1.5 text-[11px] text-white/70 outline-none focus:border-gold/40 transition-colors cursor-pointer"
        >
          <option value="all">All Ratings</option>
          <option value="recommended">Recommended</option>
          <option value="available">Available</option>
          <option value="not_recommended">Not Recommended</option>
          <option value="none">No Rating</option>
        </select>

        {/* Visibility filter */}
        <select
          value={visibilityFilter}
          onChange={(e) => setVisibilityFilter(e.target.value as VisibilityFilter)}
          aria-label="Filter by visibility"
          className="rounded-lg border border-white/8 bg-elevated px-2 py-1.5 text-[11px] text-white/70 outline-none focus:border-gold/40 transition-colors cursor-pointer"
        >
          <option value="all">All Visibility</option>
          <option value="visible">Visible</option>
          <option value="hidden">Hidden</option>
        </select>

        {/* Context range */}
        <div className="flex items-center gap-1 text-[10px] text-white/40">
          <span>Ctx:</span>
          <input
            type="text"
            inputMode="numeric"
            value={ctxMin}
            onChange={(e) => setCtxMin(e.target.value.replace(/[^0-9]/g, ''))}
            aria-label="Minimum context window in thousands"
            placeholder="min"
            className="w-20 rounded border border-white/8 bg-elevated px-1.5 py-1 text-[10px] text-white/70 outline-none focus:border-gold/40 transition-colors"
          />
          <span>-</span>
          <input
            type="text"
            inputMode="numeric"
            value={ctxMax}
            onChange={(e) => setCtxMax(e.target.value.replace(/[^0-9]/g, ''))}
            aria-label="Maximum context window in thousands"
            placeholder="max"
            className="w-20 rounded border border-white/8 bg-elevated px-1.5 py-1 text-[10px] text-white/70 outline-none focus:border-gold/40 transition-colors"
          />
          <span className="text-white/20">k</span>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
              <th
                onClick={() => toggleSort("provider")}
                className="cursor-pointer px-4 py-2 font-medium hover:text-white/50 transition-colors"
              >
                Provider{sortIndicator("provider")}
              </th>
              <th
                onClick={() => toggleSort("name")}
                className="cursor-pointer px-4 py-2 font-medium hover:text-white/50 transition-colors"
              >
                Name{sortIndicator("name")}
              </th>
              <th
                onClick={() => toggleSort("params")}
                className="cursor-pointer px-4 py-2 font-medium hover:text-white/50 transition-colors"
              >
                Params{sortIndicator("params")}
              </th>
              <th
                onClick={() => toggleSort("context")}
                className="cursor-pointer px-4 py-2 font-medium hover:text-white/50 transition-colors"
              >
                Context{sortIndicator("context")}
              </th>
              <th className="px-4 py-2 font-medium">Caps</th>
              <th className="px-4 py-2 font-medium">Rating</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-[12px] text-white/60">
                  No models match your filters
                </td>
              </tr>
            )}
            {sorted.map((model) => (
              <tr
                key={model.unique_id}
                onClick={() => onSelectModel(model)}
                className="cursor-pointer border-b border-white/6 transition-colors hover:bg-white/4"
              >
                {/* Provider */}
                <td className="px-4 py-2 text-[11px] text-white/40">
                  {model.provider_display_name}
                </td>

                {/* Name + hidden badge */}
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-white/80">{model.display_name}</span>
                    {model.curation?.hidden && (
                      <span className="rounded bg-white/6 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-white/60">
                        Hidden
                      </span>
                    )}
                  </div>
                </td>

                {/* Params + quantisation */}
                <td className="px-4 py-2">
                  <span className="text-[12px] font-medium text-white/70">
                    {model.parameter_count ?? "-"}
                  </span>
                  {model.quantisation_level && (
                    <span className="ml-1 text-[10px] text-white/30">
                      {model.quantisation_level}
                    </span>
                  )}
                </td>

                {/* Context window */}
                <td className="px-4 py-2 text-[12px] text-white/55">
                  {formatContext(model.context_window)}
                </td>

                {/* Capabilities */}
                <td className="px-4 py-2">
                  <div className="flex items-center gap-1">
                    {model.supports_tool_calls && (
                      <span className="text-[10px] font-bold text-[#a6e3a1]" title="Tool Calls">T</span>
                    )}
                    {model.supports_vision && (
                      <span className="text-[10px] font-bold text-[#89b4fa]" title="Vision">V</span>
                    )}
                    {model.supports_reasoning && (
                      <span className="text-[10px] font-bold text-[#f9e2af]" title="Reasoning">R</span>
                    )}
                  </div>
                </td>

                {/* Rating */}
                <td className="px-4 py-2">
                  {model.curation ? (
                    <span
                      className={[
                        "rounded-full border px-2 py-0.5 text-[10px] font-medium",
                        RATING_COLOURS[model.curation.overall_rating],
                      ].join(" ")}
                    >
                      {RATING_LABELS[model.curation.overall_rating]}
                    </span>
                  ) : (
                    <span className="text-[10px] text-white/60">-</span>
                  )}
                </td>

              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-white/6 px-4 py-2">
        <span className="text-[10px] text-white/60">
          {filtered.length} of {models.length} models
        </span>
        <span className="text-[10px] text-white/60">
          Click a row to curate
        </span>
      </div>
    </div>
  )
}
