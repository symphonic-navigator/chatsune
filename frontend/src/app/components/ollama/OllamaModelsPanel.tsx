import { useCallback, useEffect, useRef, useState } from "react"
import { usePullProgressStore, type PullEntry } from "../../../core/store/pullProgressStore"
import { eventBus } from "../../../core/websocket/eventBus"
import type { BaseEvent } from "../../../core/types/events"
import type {
  OllamaPsResponse,
  OllamaTagsResponse,
  StartPullResponse,
  ListPullsResponse,
  OllamaPsModel,
  OllamaTagModel,
} from "../../../core/api/ollamaLocal"
import { ApiError } from "../../../core/api/client"

export interface OllamaEndpoints {
  ps: () => Promise<OllamaPsResponse>
  tags: () => Promise<OllamaTagsResponse>
  pull: (slug: string) => Promise<StartPullResponse>
  cancelPull: (pullId: string) => Promise<void>
  deleteModel: (name: string) => Promise<void>
  listPulls: () => Promise<ListPullsResponse>
}

interface Props {
  scope: string
  endpoints: OllamaEndpoints
}

type OllamaSubtab = "ps" | "tags"

const SUBTABS: { id: OllamaSubtab; label: string }[] = [
  { id: "ps", label: "Running (ps)" },
  { id: "tags", label: "Models (tags)" },
]

const POLL_INTERVAL_MS = 5000

export function OllamaModelsPanel({ scope, endpoints }: Props) {
  const [activeSubtab, setActiveSubtab] = useState<OllamaSubtab>("tags")
  const [psData, setPsData] = useState<OllamaPsResponse | null>(null)
  const [tagsData, setTagsData] = useState<OllamaTagsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [pullSlug, setPullSlug] = useState("")
  const [pullInFlight, setPullInFlight] = useState(false)

  const inFlightRef = useRef<Promise<void> | null>(null)

  const activePullsMap = usePullProgressStore((s) => s.byScope[scope] ?? {})
  const activePulls: PullEntry[] = Object.values(activePullsMap)

  const fetchData = useCallback(
    async (subtab: OllamaSubtab) => {
      if (inFlightRef.current) return inFlightRef.current
      const promise = (async () => {
        try {
          if (subtab === "ps") {
            const data = await endpoints.ps()
            setPsData(data)
          } else {
            const data = await endpoints.tags()
            setTagsData(data)
          }
          setError(null)
          setLastUpdated(new Date())
        } catch (err) {
          if (err instanceof ApiError && [404, 502, 503, 504].includes(err.status)) {
            setError("No connection to Ollama")
          } else {
            setError(err instanceof Error ? err.message : "Failed to fetch data")
          }
        } finally {
          setLoading(false)
          inFlightRef.current = null
        }
      })()
      inFlightRef.current = promise
      return promise
    },
    [endpoints],
  )

  const refreshTags = useCallback(async () => {
    try {
      const data = await endpoints.tags()
      setTagsData(data)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      if (err instanceof ApiError && [404, 502, 503, 504].includes(err.status)) {
        setError("No connection to Ollama")
      } else {
        setError(err instanceof Error ? err.message : "Failed to fetch data")
      }
    }
  }, [endpoints])

  // Hydrate active pulls on mount
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const resp = await endpoints.listPulls()
        if (cancelled) return
        usePullProgressStore.getState().hydrateFromList(scope, resp.pulls)
      } catch {
        // Ignore network errors silently
      }
    })()
    return () => {
      cancelled = true
    }
  }, [scope, endpoints])

  // Fetch on mount + subtab change, poll every 5s
  useEffect(() => {
    setLoading(true)
    fetchData(activeSubtab)
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") fetchData(activeSubtab)
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [activeSubtab, fetchData])

  // Refresh tags on terminal pull / delete events for this scope
  useEffect(() => {
    const handle = (event: BaseEvent) => {
      const payload = event.payload as { scope?: string }
      if (payload?.scope !== scope) return
      void refreshTags()
    }
    const offCompleted = eventBus.on("llm.model.pull.completed", handle)
    const offDeleted = eventBus.on("llm.model.deleted", handle)
    return () => {
      offCompleted()
      offDeleted()
    }
  }, [scope, refreshTags])

  const handleDelete = useCallback(
    async (name: string) => {
      if (!window.confirm(`Delete model \`${name}\`?`)) return
      try {
        await endpoints.deleteModel(name)
        await refreshTags()
      } catch (err) {
        if (err instanceof ApiError && [404, 502, 503, 504].includes(err.status)) {
          setError("No connection to Ollama")
        } else {
          setError(err instanceof Error ? err.message : "Failed to delete model")
        }
      }
    },
    [endpoints, refreshTags],
  )

  const handlePull = useCallback(
    async (ev: React.FormEvent<HTMLFormElement>) => {
      ev.preventDefault()
      const slug = pullSlug.trim()
      if (!slug || pullInFlight) return
      setPullInFlight(true)
      try {
        await endpoints.pull(slug)
        setPullSlug("")
      } catch (err) {
        if (err instanceof ApiError && [404, 502, 503, 504].includes(err.status)) {
          setError("No connection to Ollama")
        } else {
          setError(err instanceof Error ? err.message : "Failed to start pull")
        }
      } finally {
        setPullInFlight(false)
      }
    },
    [endpoints, pullSlug, pullInFlight],
  )

  const handleCancelPull = useCallback(
    async (pullId: string) => {
      try {
        await endpoints.cancelPull(pullId)
      } catch (err) {
        if (err instanceof ApiError && [404, 502, 503, 504].includes(err.status)) {
          setError("No connection to Ollama")
        } else {
          setError(err instanceof Error ? err.message : "Failed to cancel pull")
        }
      }
    },
    [endpoints],
  )

  const isDisconnected = error === "No connection to Ollama"

  if (loading && !psData && !tagsData) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Connecting to Ollama...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Subtab bar */}
      <div
        role="tablist"
        aria-label="Ollama sections"
        className="flex items-center justify-between border-b border-white/6 px-4 flex-shrink-0"
      >
        <div className="flex">
          {SUBTABS.map((tab) => {
            const selected = activeSubtab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                tabIndex={selected ? 0 : -1}
                onClick={() => setActiveSubtab(tab.id)}
                className={[
                  "px-3 py-2 text-[11px] border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap",
                  selected
                    ? "border-gold text-gold"
                    : "border-transparent text-white/60 hover:text-white/80",
                ].join(" ")}
              >
                {tab.label}
              </button>
            )
          })}
        </div>
        {lastUpdated && !isDisconnected && (
          <span className="text-[10px] text-white/40 tabular-nums">
            updated {lastUpdated.toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isDisconnected ? (
          <div className="flex flex-1 items-center justify-center py-20">
            <span className="text-[13px] text-white/40">No connection to Ollama</span>
          </div>
        ) : (
          <>
            {activeSubtab === "ps" && psData && <PsView models={psData.models} />}
            {activeSubtab === "tags" && tagsData && (
              <TagsView models={tagsData.models} onDelete={handleDelete} />
            )}

            {activeSubtab === "tags" && (
              <div className="border-t border-white/6 px-4 py-3">
                <form onSubmit={handlePull} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={pullSlug}
                    onChange={(e) => setPullSlug(e.target.value)}
                    placeholder="Model slug (e.g. llama3.2:3b)"
                    className="flex-1 rounded border border-white/10 bg-black/20 px-2 py-1 text-[12px] text-white/80 placeholder:text-white/30 focus:border-gold/50 focus:outline-none"
                  />
                  <button
                    type="submit"
                    disabled={pullSlug.trim().length === 0 || pullInFlight}
                    className="rounded border border-gold/40 bg-gold/10 px-3 py-1 text-[11px] text-gold transition-colors hover:bg-gold/20 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Pull
                  </button>
                </form>
              </div>
            )}

            {activePulls.length > 0 && (
              <div className="border-t border-white/6 px-4 py-3">
                <div className="mb-2 text-[10px] uppercase tracking-wider text-white/60">
                  Active pulls
                </div>
                <div className="flex flex-col gap-2">
                  {activePulls.map((entry) => (
                    <ActivePullRow
                      key={entry.pullId}
                      entry={entry}
                      onCancel={() => handleCancelPull(entry.pullId)}
                    />
                  ))}
                </div>
              </div>
            )}

            {error && !isDisconnected && (
              <div className="border-t border-white/6 px-4 py-2">
                <span className="text-[11px] text-red-400">{error}</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  const value = bytes / Math.pow(1024, i)
  return `${value.toFixed(1)} ${units[i]}`
}

function formatNumber(n: number): string {
  return n.toLocaleString("en-US")
}

// ─── Sub-views ───────────────────────────────────────────────────────

function PsView({ models }: { models: OllamaPsModel[] }) {
  if (models.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center py-10">
        <span className="text-[12px] text-white/40">No models currently running</span>
      </div>
    )
  }

  return (
    <table className="w-full text-left">
      <thead className="sticky top-0 z-10 bg-surface">
        <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
          <Th>Name</Th>
          <Th>Model</Th>
          <Th align="right">Size</Th>
          <Th>Parameters</Th>
          <Th>Quantisation</Th>
          <Th align="right">VRAM</Th>
          <Th align="right">Context</Th>
        </tr>
      </thead>
      <tbody>
        {models.map((m, i) => (
          <tr
            key={`${m.name}-${i}`}
            className="border-b border-white/6 transition-colors hover:bg-white/4"
          >
            <Td><span className="font-mono text-[11px] text-white/80">{m.name}</span></Td>
            <Td><span className="font-mono text-[11px] text-white/60">{m.model}</span></Td>
            <Td align="right"><span className="font-mono text-[11px] tabular-nums text-white/60">{formatBytes(m.size)}</span></Td>
            <Td><span className="font-mono text-[11px] text-white/60">{m.details.parameter_size}</span></Td>
            <Td><span className="font-mono text-[11px] text-white/60">{m.details.quantization_level}</span></Td>
            <Td align="right"><span className="font-mono text-[11px] tabular-nums text-white/60">{formatBytes(m.size_vram)}</span></Td>
            <Td align="right"><span className="font-mono text-[11px] tabular-nums text-white/60">{formatNumber(m.context_length)}</span></Td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function TagsView({
  models,
  onDelete,
}: {
  models: OllamaTagModel[]
  onDelete: (name: string) => void
}) {
  if (models.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center py-10">
        <span className="text-[12px] text-white/40">No models available</span>
      </div>
    )
  }

  return (
    <table className="w-full text-left">
      <thead className="sticky top-0 z-10 bg-surface">
        <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
          <Th>Name</Th>
          <Th>Model</Th>
          <Th align="right">Size</Th>
          <Th>Parameters</Th>
          <Th>Quantisation</Th>
          <Th align="right">Actions</Th>
        </tr>
      </thead>
      <tbody>
        {models.map((m, i) => (
          <tr
            key={`${m.name}-${i}`}
            className="border-b border-white/6 transition-colors hover:bg-white/4"
          >
            <Td><span className="font-mono text-[11px] text-white/80">{m.name}</span></Td>
            <Td><span className="font-mono text-[11px] text-white/60">{m.model}</span></Td>
            <Td align="right"><span className="font-mono text-[11px] tabular-nums text-white/60">{formatBytes(m.size)}</span></Td>
            <Td><span className="font-mono text-[11px] text-white/60">{m.details.parameter_size}</span></Td>
            <Td><span className="font-mono text-[11px] text-white/60">{m.details.quantization_level}</span></Td>
            <Td align="right">
              <button
                type="button"
                onClick={() => onDelete(m.name)}
                className="rounded border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-300 transition-colors hover:bg-red-500/20"
              >
                Delete
              </button>
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ActivePullRow({
  entry,
  onCancel,
}: {
  entry: PullEntry
  onCancel: () => void
}) {
  const showProgress =
    entry.completed != null && entry.total != null && entry.total > 0
  return (
    <div className="flex items-center gap-3">
      <span className="font-mono text-[11px] text-white/80 min-w-[10rem] truncate">
        {entry.slug}
      </span>
      <span className="font-mono text-[10px] text-white/50 min-w-[6rem] truncate">
        {entry.status}
      </span>
      {showProgress && (
        <progress
          value={entry.completed ?? 0}
          max={entry.total ?? 1}
          className="flex-1 h-2"
        />
      )}
      {!showProgress && <span className="flex-1" />}
      <button
        type="button"
        onClick={onCancel}
        aria-label="Cancel pull"
        className="rounded border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/70 transition-colors hover:bg-white/10"
      >
        ×
      </button>
    </div>
  )
}

// ─── Reusable table atoms ────────────────────────────────────────────

function Th({ children, align }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th className={["px-4 py-2 font-medium", align === "right" ? "text-right" : "text-left"].join(" ")}>
      {children}
    </th>
  )
}

function Td({ children, align }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <td className={["px-4 py-2", align === "right" ? "text-right" : "text-left"].join(" ")}>
      {children}
    </td>
  )
}
