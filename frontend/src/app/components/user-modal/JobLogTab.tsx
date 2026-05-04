import { useEffect, useMemo, useState } from 'react'

import { fetchJobLog } from '../../../core/api/jobsLog'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics, type BaseEvent } from '../../../core/types/events'
import type { JobLogEntry, JobLogStatus } from '../../../core/types/jobLog'

const MAX_ENTRIES = 200

const JOB_TYPE_LABELS: Record<string, string> = {
  memory_extraction: 'Memory extraction',
  memory_consolidation: 'Memory consolidation',
  title_generation: 'Title generation',
}

const STATUS_STYLE: Record<JobLogStatus, string> = {
  started: 'text-white/60',
  completed: 'text-green-400/80',
  failed: 'text-red-400/80',
  retry: 'text-amber-400/80',
}

const STATUS_LABEL: Record<JobLogStatus, string> = {
  started: 'started',
  completed: 'completed',
  failed: 'failed',
  retry: 'retry',
}

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

function relativeTime(fromIso: string, now: number): string {
  const then = Date.parse(fromIso)
  const diffS = Math.max(0, Math.floor((now - then) / 1000))
  if (diffS < 60) return `${diffS}s ago`
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m ago`
  if (diffS < 86400) return `${Math.floor(diffS / 3600)}h ago`
  return `${Math.floor(diffS / 86400)}d ago`
}

function absoluteTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString()
}

function labelFor(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] ?? jobType
}

interface JobEventPayload {
  job_id?: string
  job_type?: string
  persona_id?: string | null
  attempt?: number
  notify?: boolean
  error_message?: string
}

function statusFromEventType(type: string): JobLogStatus | null {
  if (type === Topics.JOB_STARTED) return 'started'
  if (type === Topics.JOB_COMPLETED) return 'completed'
  if (type === Topics.JOB_FAILED) return 'failed'
  if (type === Topics.JOB_RETRY) return 'retry'
  return null
}

function entryFromEvent(event: BaseEvent): JobLogEntry | null {
  const status = statusFromEventType(event.type)
  if (!status) return null
  const p = (event.payload ?? {}) as JobEventPayload
  if (!p.job_id || !p.job_type) return null
  return {
    entry_id: event.id,
    job_id: p.job_id,
    job_type: p.job_type,
    persona_id: p.persona_id ?? null,
    status,
    attempt: p.attempt ?? 0,
    silent: p.notify === false,
    ts:
      typeof event.timestamp === 'string'
        ? event.timestamp
        : new Date().toISOString(),
    duration_ms: null,
    error_message: p.error_message ?? null,
  }
}

type PersonaFilter = 'all' | 'none' | string

export function JobLogTab() {
  const [entries, setEntries] = useState<JobLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [personaFilter, setPersonaFilter] = useState<PersonaFilter>('all')
  const [showSilent, setShowSilent] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [now, setNow] = useState(() => Date.now())
  const { personas } = usePersonas()

  useEffect(() => {
    let cancelled = false
    fetchJobLog(MAX_ENTRIES)
      .then((data) => {
        if (cancelled) return
        setEntries(data)
        setError(null)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Unknown error')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const handler = (event: BaseEvent) => {
      const entry = entryFromEvent(event)
      if (!entry) return
      setEntries((prev) => {
        if (prev.some((e) => e.entry_id === entry.entry_id)) return prev
        const next = [entry, ...prev]
        return next.length > MAX_ENTRIES ? next.slice(0, MAX_ENTRIES) : next
      })
    }
    const unsub = eventBus.on('job.*', handler)
    return () => {
      unsub()
    }
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(id)
  }, [])

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (!showSilent && e.silent) return false
      if (personaFilter === 'all') return true
      if (personaFilter === 'none') return !e.persona_id
      return e.persona_id === personaFilter
    })
  }, [entries, personaFilter, showSilent])

  const toggleExpanded = (entryId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(entryId)) next.delete(entryId)
      else next.add(entryId)
      return next
    })
  }

  return (
    <div className="flex flex-col gap-4 overflow-y-auto">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-white/30 font-mono uppercase tracking-wider mr-1">
            Persona
          </span>
          <select
            value={personaFilter}
            onChange={(e) => setPersonaFilter(e.target.value)}
            className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
            style={{
              backgroundImage:
                'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 12 12%27%3E%3Cpath d=%27M3 5l3 3 3-3%27 fill=%27none%27 stroke=%27rgba(255,255,255,0.3)%27 stroke-width=%271.5%27/%3E%3C/svg%3E")',
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 6px center',
            }}
          >
            <option value="all" style={OPTION_STYLE}>All</option>
            <option value="none" style={OPTION_STYLE}>No persona</option>
            {personas.map((p) => (
              <option key={p.id} value={p.id} style={OPTION_STYLE}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          onClick={() => setShowSilent((v) => !v)}
          className={
            showSilent
              ? 'rounded-lg border border-gold/40 bg-gold/10 px-2 py-1 text-[11px] font-mono text-gold/90'
              : 'rounded-lg border border-white/8 bg-surface px-2 py-1 text-[11px] font-mono text-white/50 hover:text-white/70'
          }
          title="Show silent jobs (title generation etc.)"
        >
          Silent: {showSilent ? 'on' : 'off'}
        </button>

        <div className="ml-auto text-[10px] text-white/30 font-mono">
          {filtered.length} entr{filtered.length === 1 ? 'y' : 'ies'}
        </div>
      </div>

      {loading && (
        <div className="text-[11px] text-white/40 font-mono">Loading…</div>
      )}
      {error && (
        <div className="text-[11px] text-red-400/80 font-mono">Error: {error}</div>
      )}
      {!loading && !error && filtered.length === 0 && (
        <div className="text-[11px] text-white/30 font-mono">
          No entries match the current filter.
        </div>
      )}

      <div className="flex flex-col divide-y divide-white/5 border border-white/8 rounded-lg overflow-hidden">
        {filtered.map((entry) => {
          const persona = entry.persona_id
            ? personas.find((p) => p.id === entry.persona_id)?.name ?? entry.persona_id
            : null
          const isExpandable = entry.status === 'failed' && !!entry.error_message
          const isOpen = expanded.has(entry.entry_id)
          return (
            <div key={entry.entry_id} className="flex flex-col px-3 py-2">
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span className={`${STATUS_STYLE[entry.status]} w-[70px]`}>
                  {STATUS_LABEL[entry.status]}
                </span>
                <span className="text-white/80 w-[150px] truncate">
                  {labelFor(entry.job_type)}
                </span>
                <span className="text-white/50 w-[120px] truncate">
                  {persona ?? '—'}
                </span>
                <span className="text-white/40" title={absoluteTime(entry.ts)}>
                  {relativeTime(entry.ts, now)} · {absoluteTime(entry.ts)}
                </span>
                {entry.duration_ms != null && (
                  <span className="text-white/30">{entry.duration_ms} ms</span>
                )}
                {entry.attempt > 0 && (
                  <span className="text-amber-400/70">attempt {entry.attempt}</span>
                )}
                {entry.silent && <span className="text-white/25">silent</span>}
                {isExpandable && (
                  <button
                    type="button"
                    onClick={() => toggleExpanded(entry.entry_id)}
                    className="ml-auto text-white/40 hover:text-white/70"
                  >
                    {isOpen ? 'hide' : 'details'}
                  </button>
                )}
              </div>
              {isExpandable && isOpen && (
                <pre className="mt-2 whitespace-pre-wrap break-words bg-black/30 border border-white/5 rounded px-2 py-1.5 text-[10px] text-red-300/80 font-mono">
                  {entry.error_message}
                </pre>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
