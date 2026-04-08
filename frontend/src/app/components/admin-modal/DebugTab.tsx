// Admin debug overlay — diagnostic view of background work + LLM inference.
//
// Built specifically to investigate "GPU pegged at 100% while backend idle"
// — see CLAUDE.md / commit history for context. Shows four sub-views:
//   1. Inferences   — currently in-flight LLM calls (model + user + source)
//   2. Jobs         — pending / running / retry-pending background jobs
//   3. Locks        — per-user job locks currently held in this process
//   4. Queues       — Redis Stream queue depth + embedding worker queues
//
// Live updates: subscribes to debug.* and job.* events on the WebSocket
// event bus and re-fetches the snapshot whenever any of them fire. A 2s
// polling fallback covers state changes that do not flow through events
// (queue depth fluctuations, lock acquire/release, etc.).

import { useCallback, useEffect, useRef, useState } from "react"
import { debugApi } from "../../../core/api/debug"
import { eventBus } from "../../../core/websocket/eventBus"
import { Topics } from "../../../core/types/events"
import type {
  ActiveInferenceDto,
  DebugSnapshotDto,
  JobSnapshotDto,
  JobStatus,
  LockSnapshotDto,
} from "../../../core/types/debug"

type DebugSubtab = "inferences" | "jobs" | "locks" | "queues"

interface Subtab {
  id: DebugSubtab
  label: string
  count?: (s: DebugSnapshotDto) => number
}

const SUBTABS: Subtab[] = [
  { id: "inferences", label: "Inferences", count: (s) => s.active_inferences.length },
  { id: "jobs", label: "Jobs", count: (s) => s.jobs.length },
  { id: "locks", label: "Locks", count: (s) => s.locks.length },
  { id: "queues", label: "Queues" },
]

const POLL_INTERVAL_MS = 2000
// Trailing-edge debounce window for event-driven refetches. A burst of
// debug/job events (e.g. a stuck job retry-looping, or heavy embedding
// traffic) would otherwise trigger dozens of setState calls per second,
// re-rendering the tab constantly. Collapsing bursts into one fetch per
// this window keeps the UI usable without losing fidelity in practice —
// the 2s poll fallback ensures we still catch the final state.
const EVENT_DEBOUNCE_MS = 750

// Topics that should immediately trigger a re-fetch — anything that
// changes job state or inference state.
const TRIGGER_TOPICS = [
  Topics.DEBUG_INFERENCE_STARTED,
  Topics.DEBUG_INFERENCE_FINISHED,
  Topics.JOB_STARTED,
  Topics.JOB_COMPLETED,
  Topics.JOB_FAILED,
  Topics.JOB_RETRY,
  Topics.JOB_EXPIRED,
] as const

export function DebugTab() {
  const [snapshot, setSnapshot] = useState<DebugSnapshotDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeSubtab, setActiveSubtab] = useState<DebugSubtab>("inferences")

  // Coalesce rapid bursts of events / polls into a single fetch in flight.
  const inFlightRef = useRef<Promise<void> | null>(null)

  const fetchSnapshot = useCallback(async () => {
    if (inFlightRef.current) return inFlightRef.current
    const promise = (async () => {
      try {
        const data = await debugApi.snapshot()
        setSnapshot(data)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch snapshot")
      } finally {
        setLoading(false)
        inFlightRef.current = null
      }
    })()
    inFlightRef.current = promise
    return promise
  }, [])

  // Trailing-edge debounce: multiple calls within EVENT_DEBOUNCE_MS
  // collapse into a single fetch fired at the end of the window.
  const debounceTimerRef = useRef<number | null>(null)
  const scheduleFetch = useCallback(() => {
    if (debounceTimerRef.current !== null) return
    debounceTimerRef.current = window.setTimeout(() => {
      debounceTimerRef.current = null
      fetchSnapshot()
    }, EVENT_DEBOUNCE_MS)
  }, [fetchSnapshot])

  // Initial fetch + 2s polling fallback for non-event-driven state changes.
  // Polling pauses when the document is hidden — no point hammering the
  // backend when nobody is looking, and it also means the tab does not
  // accumulate stale updates in the background.
  useEffect(() => {
    fetchSnapshot()
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") fetchSnapshot()
    }, POLL_INTERVAL_MS)
    return () => {
      window.clearInterval(interval)
      if (debounceTimerRef.current !== null) {
        window.clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
    }
  }, [fetchSnapshot])

  // Live event subscriptions: schedule a debounced re-fetch on any
  // debug.* or job.* event. Bursts collapse into one fetch per window.
  useEffect(() => {
    const unsubs = TRIGGER_TOPICS.map((topic) =>
      eventBus.on(topic, () => {
        scheduleFetch()
      }),
    )
    return () => {
      for (const u of unsubs) u()
    }
  }, [scheduleFetch])

  if (loading && !snapshot) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Loading debug snapshot...</span>
        </div>
      </div>
    )
  }

  if (error && !snapshot) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <span className="text-[12px] text-red-400">{error}</span>
        <button
          type="button"
          onClick={fetchSnapshot}
          className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[11px] font-medium text-gold transition-colors hover:bg-gold/20 cursor-pointer"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!snapshot) return null

  const generatedAt = new Date(snapshot.generated_at)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Subtab bar */}
      <div
        role="tablist"
        aria-label="Debug sections"
        className="flex items-center justify-between border-b border-white/6 px-4 flex-shrink-0"
      >
        <div className="flex">
          {SUBTABS.map((tab) => {
            const selected = activeSubtab === tab.id
            const count = tab.count ? tab.count(snapshot) : undefined
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                tabIndex={selected ? 0 : -1}
                onClick={() => setActiveSubtab(tab.id)}
                className={[
                  "px-3 py-2 text-[11px] border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap flex items-center gap-1.5",
                  selected
                    ? "border-gold text-gold"
                    : "border-transparent text-white/60 hover:text-white/80",
                ].join(" ")}
              >
                <span>{tab.label}</span>
                {count !== undefined && (
                  <span
                    className={[
                      "rounded px-1.5 py-0.5 text-[9px] tabular-nums border",
                      count > 0
                        ? "border-gold/30 bg-gold/10 text-gold"
                        : "border-white/10 bg-white/4 text-white/40",
                    ].join(" ")}
                  >
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] text-white/40 tabular-nums"
            title={`Snapshot generated at ${generatedAt.toISOString()}`}
          >
            updated {generatedAt.toLocaleTimeString()}
          </span>
          <button
            type="button"
            onClick={fetchSnapshot}
            className="rounded border border-white/8 px-2 py-0.5 text-[10px] text-white/60 transition-colors hover:bg-white/6 hover:text-white/80 cursor-pointer"
            aria-label="Refresh snapshot"
          >
            REFRESH
          </button>
        </div>
      </div>

      {/* Error banner (non-fatal — snapshot still rendered from last successful fetch) */}
      {error && snapshot && (
        <div className="flex items-center justify-between border-b border-red-400/20 bg-red-400/5 px-4 py-1.5">
          <span className="text-[10px] text-red-400">Last refresh failed: {error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-[10px] text-red-400/60 hover:text-red-400 transition-colors cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Subtab content */}
      <div className="flex-1 overflow-auto">
        {activeSubtab === "inferences" && <InferencesView items={snapshot.active_inferences} />}
        {activeSubtab === "jobs" && <JobsView items={snapshot.jobs} />}
        {activeSubtab === "locks" && <LocksView items={snapshot.locks} />}
        {activeSubtab === "queues" && <QueuesView snapshot={snapshot} />}
      </div>
    </div>
  )
}

// ─── Subtab views ────────────────────────────────────────────────────

function InferencesView({ items }: { items: ActiveInferenceDto[] }) {
  if (items.length === 0) {
    return <EmptyState message="No active LLM inferences" />
  }

  return (
    <table className="w-full text-left">
      <thead className="sticky top-0 z-10 bg-surface">
        <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
          <Th>User</Th>
          <Th>Model</Th>
          <Th>Source</Th>
          <Th align="right">Duration</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((inf) => (
          <tr
            key={inf.inference_id}
            className="border-b border-white/6 transition-colors hover:bg-white/4"
          >
            <Td>
              <UserCell username={inf.username} userId={inf.user_id} />
            </Td>
            <Td>
              <span className="font-mono text-[11px] text-white/80">{inf.model_unique_id}</span>
            </Td>
            <Td>
              <SourceBadge source={inf.source} />
            </Td>
            <Td align="right">
              <span className="font-mono text-[11px] tabular-nums text-white/60">
                {formatDuration(inf.duration_seconds)}
              </span>
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function JobsView({ items }: { items: JobSnapshotDto[] }) {
  if (items.length === 0) {
    return <EmptyState message="No background jobs queued or running" />
  }

  return (
    <table className="w-full text-left">
      <thead className="sticky top-0 z-10 bg-surface">
        <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
          <Th>Status</Th>
          <Th>Type</Th>
          <Th>User</Th>
          <Th>Model</Th>
          <Th align="right">Attempt</Th>
          <Th align="right">Age</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((job) => (
          <tr
            key={job.job_id}
            className="border-b border-white/6 transition-colors hover:bg-white/4"
            title={`job_id=${job.job_id}\ncorrelation_id=${job.correlation_id}`}
          >
            <Td>
              <JobStatusBadge status={job.status} nextRetryAt={job.next_retry_at} />
            </Td>
            <Td>
              <span className="font-mono text-[11px] text-white/80">{job.job_type}</span>
            </Td>
            <Td>
              <UserCell username={job.username} userId={job.user_id} />
            </Td>
            <Td>
              <span className="font-mono text-[11px] text-white/60">{job.model_unique_id}</span>
            </Td>
            <Td align="right">
              <span className="font-mono text-[11px] tabular-nums text-white/60">
                {job.attempt}
                {job.max_retries !== null && (
                  <span className="text-white/30">/{job.max_retries}</span>
                )}
              </span>
            </Td>
            <Td align="right">
              <span className="font-mono text-[11px] tabular-nums text-white/60">
                {formatDuration(job.age_seconds)}
              </span>
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function LocksView({ items }: { items: LockSnapshotDto[] }) {
  if (items.length === 0) {
    return <EmptyState message="No locks currently held" />
  }

  return (
    <table className="w-full text-left">
      <thead className="sticky top-0 z-10 bg-surface">
        <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
          <Th>Kind</Th>
          <Th>User</Th>
        </tr>
      </thead>
      <tbody>
        {items.map((lock, i) => (
          <tr
            key={`${lock.kind}:${lock.user_id}:${i}`}
            className="border-b border-white/6 transition-colors hover:bg-white/4"
          >
            <Td>
              <LockKindBadge kind={lock.kind} />
            </Td>
            <Td>
              <UserCell username={lock.username} userId={lock.user_id} />
            </Td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function QueuesView({ snapshot }: { snapshot: DebugSnapshotDto }) {
  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Stream queues */}
      <section>
        <h3 className="text-[10px] uppercase tracking-[0.15em] text-white/60 mb-2">
          Job Queues
        </h3>
        <div className="rounded-lg border border-white/8 bg-white/4 overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
                <Th>Name</Th>
                <Th align="right">Length</Th>
                <Th align="right">Pending</Th>
                <Th align="right">Oldest age</Th>
              </tr>
            </thead>
            <tbody>
              {snapshot.stream_queues.map((q) => (
                <tr key={q.name} className="border-b border-white/6 last:border-b-0">
                  <Td>
                    <span className="font-mono text-[11px] text-white/80">{q.name}</span>
                  </Td>
                  <Td align="right">
                    <Metric value={q.stream_length} />
                  </Td>
                  <Td align="right">
                    <Metric value={q.pending_count} highlight={q.pending_count > 0} />
                  </Td>
                  <Td align="right">
                    <span className="font-mono text-[11px] tabular-nums text-white/60">
                      {q.oldest_pending_age_seconds === null
                        ? "—"
                        : formatDuration(q.oldest_pending_age_seconds)}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Embedding worker */}
      <section>
        <h3 className="text-[10px] uppercase tracking-[0.15em] text-white/60 mb-2">
          Embedding Worker
        </h3>
        <div className="rounded-lg border border-white/8 bg-white/4 p-3">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[11px]">
            <div className="flex justify-between">
              <span className="text-white/60">Model loaded</span>
              <span
                className={
                  snapshot.embedding_queue.model_loaded ? "text-green-400" : "text-red-400"
                }
              >
                {snapshot.embedding_queue.model_loaded ? "yes" : "no"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/60">Model</span>
              <span className="font-mono text-white/80">
                {snapshot.embedding_queue.model_name || "—"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-white/60">Query queue</span>
              <Metric value={snapshot.embedding_queue.query_queue_size} />
            </div>
            <div className="flex justify-between">
              <span className="text-white/60">Embed queue</span>
              <Metric value={snapshot.embedding_queue.embed_queue_size} />
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

// ─── Reusable cells / atoms ──────────────────────────────────────────

function Th({
  children,
  align,
}: {
  children: React.ReactNode
  align?: "left" | "right"
}) {
  return (
    <th
      className={[
        "px-4 py-2 font-medium",
        align === "right" ? "text-right" : "text-left",
      ].join(" ")}
    >
      {children}
    </th>
  )
}

function Td({
  children,
  align,
}: {
  children: React.ReactNode
  align?: "left" | "right"
}) {
  return (
    <td
      className={["px-4 py-2", align === "right" ? "text-right" : "text-left"].join(" ")}
    >
      {children}
    </td>
  )
}

function UserCell({ username, userId }: { username: string | null; userId: string }) {
  if (username) {
    return (
      <span className="text-[12px] text-white/80" title={userId}>
        {username}
      </span>
    )
  }
  return (
    <span className="font-mono text-[10px] text-white/40" title={userId}>
      {userId.slice(0, 8)}…
    </span>
  )
}

function SourceBadge({ source }: { source: string }) {
  const isJob = source.startsWith("job:")
  const isVision = source === "vision_fallback"
  const cls = isJob
    ? "border-purple-400/25 bg-purple-400/15 text-purple-400"
    : isVision
      ? "border-blue-400/25 bg-blue-400/15 text-blue-400"
      : "border-gold/25 bg-gold/15 text-gold"
  return (
    <span
      className={[
        "rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider border font-mono",
        cls,
      ].join(" ")}
    >
      {source}
    </span>
  )
}

function JobStatusBadge({
  status,
  nextRetryAt,
}: {
  status: JobStatus
  nextRetryAt: string | null
}) {
  const cls =
    status === "running"
      ? "border-green-400/25 bg-green-400/15 text-green-400"
      : status === "retry_pending"
        ? "border-yellow-400/25 bg-yellow-400/15 text-yellow-400"
        : "border-white/15 bg-white/6 text-white/60"
  const label = status.replace("_", " ")
  const title =
    status === "retry_pending" && nextRetryAt
      ? `Next retry at ${new Date(nextRetryAt).toLocaleTimeString()}`
      : undefined
  return (
    <span
      className={["rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider border", cls].join(
        " ",
      )}
      title={title}
    >
      {label}
    </span>
  )
}

function LockKindBadge({ kind }: { kind: "user" | "job" }) {
  const cls =
    kind === "user"
      ? "border-blue-400/25 bg-blue-400/15 text-blue-400"
      : "border-purple-400/25 bg-purple-400/15 text-purple-400"
  return (
    <span
      className={["rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider border", cls].join(
        " ",
      )}
    >
      {kind}
    </span>
  )
}

function Metric({ value, highlight }: { value: number; highlight?: boolean }) {
  return (
    <span
      className={[
        "font-mono text-[11px] tabular-nums",
        highlight ? "text-gold" : value === 0 ? "text-white/40" : "text-white/80",
      ].join(" ")}
    >
      {value}
    </span>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-1 items-center justify-center py-10">
      <span className="text-[12px] text-white/40">{message}</span>
    </div>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m${s.toString().padStart(2, "0")}s`
  const h = Math.floor(m / 60)
  return `${h}h${(m % 60).toString().padStart(2, "0")}m`
}
