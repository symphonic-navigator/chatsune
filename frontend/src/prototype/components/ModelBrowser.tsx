import { useMemo, useState } from "react"
import type { ModelMetaDto, UserModelConfigDto } from "../../core/types/llm"

type SortField = "name" | "context"
type SortDir = "asc" | "desc"

interface ModelBrowserProps {
  models: ModelMetaDto[]
  userConfigs?: UserModelConfigDto[]
  onSelect?: (model: ModelMetaDto) => void
  onToggleFavourite?: (model: ModelMetaDto) => void
  onToggleHidden?: (model: ModelMetaDto) => void
  selectedModelId?: string | null
  showConfigActions?: boolean
}

export default function ModelBrowser({
  models,
  userConfigs = [],
  onSelect,
  onToggleFavourite,
  onToggleHidden,
  selectedModelId,
  showConfigActions = true,
}: ModelBrowserProps) {
  const [search, setSearch] = useState("")
  const [providerFilter, setProviderFilter] = useState<string | null>(null)
  const [capFilters, setCapFilters] = useState<Set<string>>(new Set())
  const [showFavourites, setShowFavourites] = useState(false)
  const [sortField, setSortField] = useState<SortField | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const configMap = useMemo(
    () => new Map(userConfigs.map((c) => [c.model_unique_id, c])),
    [userConfigs],
  )

  const providers = useMemo(
    () => [...new Set(models.map((m) => m.provider_id))],
    [models],
  )

  const toggleCap = (cap: string) => {
    setCapFilters((prev) => {
      const next = new Set(prev)
      if (next.has(cap)) next.delete(cap)
      else next.add(cap)
      return next
    })
  }

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      if (sortDir === "asc") setSortDir("desc")
      else { setSortField(null); setSortDir("asc") }
    } else {
      setSortField(field)
      setSortDir("asc")
    }
  }

  const filtered = useMemo(() => {
    let result = models

    if (search) {
      const terms = search.toLowerCase().split(/\s+/)
      result = result.filter((m) => {
        const haystack = `${m.display_name} ${m.model_id}`.toLowerCase()
        return terms.every((t) => haystack.includes(t))
      })
    }

    if (providerFilter) {
      result = result.filter((m) => m.provider_id === providerFilter)
    }

    if (capFilters.has("tools")) result = result.filter((m) => m.supports_tool_calls)
    if (capFilters.has("vision")) result = result.filter((m) => m.supports_vision)
    if (capFilters.has("reasoning")) result = result.filter((m) => m.supports_reasoning)

    if (showFavourites) {
      result = result.filter((m) => configMap.get(m.unique_id)?.is_favourite)
    }

    if (sortField) {
      result = [...result].sort((a, b) => {
        let cmp = 0
        if (sortField === "name") cmp = a.display_name.localeCompare(b.display_name)
        if (sortField === "context") cmp = a.context_window - b.context_window
        return sortDir === "desc" ? -cmp : cmp
      })
    }

    return result
  }, [models, search, providerFilter, capFilters, showFavourites, sortField, sortDir, configMap])

  const sortIndicator = (field: SortField) => {
    if (sortField !== field) return ""
    return sortDir === "asc" ? " \u2191" : " \u2193"
  }

  const capBtnClass = (cap: string, activeColour: string) =>
    `rounded px-2 py-1 text-xs font-mono ${capFilters.has(cap) ? activeColour : "bg-gray-100 text-gray-400"}`

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          placeholder="Search models..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />

        {providers.length > 1 && (
          <>
            {providers.map((pid) => (
              <button
                key={pid}
                onClick={() => setProviderFilter(providerFilter === pid ? null : pid)}
                className={`rounded px-2 py-1 text-xs ${providerFilter === pid ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"}`}
              >
                {pid}
              </button>
            ))}
          </>
        )}

        <button onClick={() => toggleCap("tools")} className={capBtnClass("tools", "bg-green-100 text-green-700")}>T</button>
        <button onClick={() => toggleCap("vision")} className={capBtnClass("vision", "bg-blue-100 text-blue-700")}>V</button>
        <button onClick={() => toggleCap("reasoning")} className={capBtnClass("reasoning", "bg-yellow-100 text-yellow-700")}>R</button>

        {showConfigActions && (
          <button
            onClick={() => setShowFavourites(!showFavourites)}
            className={`rounded px-2 py-1 text-xs ${showFavourites ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-400"}`}
          >
            Favourites
          </button>
        )}

        <span className="text-xs text-gray-400 ml-auto">{filtered.length} models</span>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th
                onClick={() => handleSort("name")}
                className="cursor-pointer px-4 py-2 text-left text-xs font-medium text-gray-500 hover:text-gray-700"
              >
                Model{sortIndicator("name")}
              </th>
              <th
                onClick={() => handleSort("context")}
                className="cursor-pointer px-4 py-2 text-left text-xs font-medium text-gray-500 hover:text-gray-700 w-24"
              >
                Context{sortIndicator("context")}
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Capabilities</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Rating</th>
              {showConfigActions && (
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => {
              const config = configMap.get(m.unique_id)
              const isSelected = m.unique_id === selectedModelId
              return (
                <tr
                  key={m.unique_id}
                  onClick={() => onSelect?.(m)}
                  className={`border-b border-gray-100 ${onSelect ? "cursor-pointer hover:bg-gray-50" : ""} ${isSelected ? "bg-blue-50 border-l-2 border-l-blue-500" : ""}`}
                >
                  <td className="px-4 py-2">
                    <div className="text-sm font-medium">{m.display_name}</div>
                    <div className="text-xs text-gray-400">{m.model_id}</div>
                  </td>
                  <td className="px-4 py-2 text-sm">{m.context_window > 0 ? `${(m.context_window / 1024).toFixed(0)}k` : "-"}</td>
                  <td className="px-4 py-2 text-sm space-x-1">
                    {m.supports_reasoning && <span className="rounded bg-yellow-50 px-1.5 py-0.5 text-xs text-yellow-600">R</span>}
                    {m.supports_vision && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">V</span>}
                    {m.supports_tool_calls && <span className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-600">T</span>}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    {m.curation ? (
                      <span className={`rounded px-2 py-0.5 text-xs ${
                        m.curation.overall_rating === "recommended" ? "bg-green-100 text-green-700" :
                        m.curation.overall_rating === "not_recommended" ? "bg-red-100 text-red-700" :
                        "bg-gray-100 text-gray-600"
                      }`}>
                        {m.curation.overall_rating}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">uncurated</span>
                    )}
                  </td>
                  {showConfigActions && (
                    <td className="px-4 py-2 text-sm space-x-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); onToggleFavourite?.(m) }}
                        className={`rounded px-2 py-1 text-xs ${config?.is_favourite ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-500"}`}
                      >
                        {config?.is_favourite ? "Favourited" : "Favourite"}
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); onToggleHidden?.(m) }}
                        className={`rounded px-2 py-1 text-xs ${config?.is_hidden ? "bg-gray-300 text-gray-700" : "bg-gray-100 text-gray-500"}`}
                      >
                        {config?.is_hidden ? "Hidden" : "Hide"}
                      </button>
                    </td>
                  )}
                </tr>
              )
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={showConfigActions ? 5 : 4} className="px-4 py-8 text-center text-sm text-gray-400">No models match filters</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
