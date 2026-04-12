import { useCallback, useEffect, useRef, useState } from "react"
import { ollamaLocalApi } from "../../../core/api/ollamaLocal"
import type {
  OllamaPsModel,
  OllamaPsResponse,
  OllamaTagModel,
  OllamaTagsResponse,
} from "../../../core/api/ollamaLocal"
import { ApiError } from "../../../core/api/client"

type OllamaSubtab = "ps" | "tags"

const SUBTABS: { id: OllamaSubtab; label: string }[] = [
  { id: "ps", label: "Running (ps)" },
  { id: "tags", label: "Models (tags)" },
]

const POLL_INTERVAL_MS = 5000

export function OllamaTab() {
  const [activeSubtab, setActiveSubtab] = useState<OllamaSubtab>("ps")
  const [psData, setPsData] = useState<OllamaPsResponse | null>(null)
  const [tagsData, setTagsData] = useState<OllamaTagsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const inFlightRef = useRef<Promise<void> | null>(null)

  const fetchData = useCallback(
    async (subtab: OllamaSubtab) => {
      if (inFlightRef.current) return inFlightRef.current
      const promise = (async () => {
        try {
          if (subtab === "ps") {
            const data = await ollamaLocalApi.ps()
            setPsData(data)
          } else {
            const data = await ollamaLocalApi.tags()
            setTagsData(data)
          }
          setError(null)
          setLastUpdated(new Date())
        } catch (err) {
          if (err instanceof ApiError && (err.status === 503 || err.status === 502 || err.status === 504)) {
            setError("No connection to Ollama Local")
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
    [],
  )

  // Fetch on mount + subtab change, poll every 5s
  useEffect(() => {
    setLoading(true)
    fetchData(activeSubtab)
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") fetchData(activeSubtab)
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [activeSubtab, fetchData])

  const isDisconnected = error === "No connection to Ollama Local"

  if (loading && !psData && !tagsData) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Connecting to Ollama Local...</span>
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
            <span className="text-[13px] text-white/40">No connection to Ollama Local</span>
          </div>
        ) : (
          <>
            {activeSubtab === "ps" && psData && <PsView models={psData.models} />}
            {activeSubtab === "tags" && tagsData && <TagsView models={tagsData.models} />}
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

function TagsView({ models }: { models: OllamaTagModel[] }) {
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
          </tr>
        ))}
      </tbody>
    </table>
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
