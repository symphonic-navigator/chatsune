import { useEffect, useRef, useState } from "react"
import { useJobStore, type RunningJob } from "../../../core/store/jobStore"
import type { PersonaDto } from "../../../core/types/persona"

const JOB_TYPE_LABELS: Record<string, string> = {
  memory_extraction: "Memory extraction",
  memory_consolidation: "Memory consolidation",
}

function labelFor(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] ?? jobType
}

function formatElapsed(startedAt: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-2 w-2 rounded-full border border-white/40 border-t-transparent animate-spin"
    />
  )
}

interface JobRowProps {
  job: RunningJob
  now: number
  personaName: string | null
}

function JobRow({ job, now, personaName }: JobRowProps) {
  const parts: string[] = []
  if (personaName) parts.push(personaName)
  parts.push(formatElapsed(job.startedAt, now))
  if (job.attempt > 0) parts.push(`retry ${job.attempt}`)

  return (
    <div className="flex flex-col gap-0.5 px-3 py-2">
      <div className="flex items-center gap-2 text-[12px] text-white/80">
        <Spinner />
        <span>{labelFor(job.jobType)}</span>
      </div>
      <div className="pl-4 text-[11px] font-mono text-white/40">
        {parts.join(" · ")}
      </div>
    </div>
  )
}

interface JobsPillProps {
  personas: PersonaDto[]
}

export function JobsPill({ personas }: JobsPillProps) {
  const jobsMap = useJobStore((s) => s.jobs)
  const jobs = Object.values(jobsMap)
  const [isOpen, setIsOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const containerRef = useRef<HTMLDivElement>(null)

  const sorted = [...jobs].sort((a, b) => a.startedAt - b.startedAt)
  const count = sorted.length

  // Close the popover automatically when the last job finishes.
  useEffect(() => {
    if (count === 0 && isOpen) setIsOpen(false)
  }, [count, isOpen])

  // Tick once per second only while the popover is open.
  useEffect(() => {
    if (!isOpen) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [isOpen])

  // Click-outside closes the popover.
  useEffect(() => {
    if (!isOpen) return
    const handleClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    document.addEventListener("keydown", handleEscape)
    return () => {
      document.removeEventListener("mousedown", handleClick)
      document.removeEventListener("keydown", handleEscape)
    }
  }, [isOpen])

  if (count === 0) return null

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        title={`${count} background job${count === 1 ? "" : "s"} running`}
        className="flex items-center gap-1.5 rounded-full border border-white/8 bg-white/4 px-2.5 py-0.5 font-mono text-[11px] text-white/55 transition-colors hover:bg-white/7"
      >
        <Spinner />
        <span>{count}</span>
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 z-50 w-[280px] overflow-hidden rounded-xl border border-white/8 bg-surface shadow-2xl">
          <div className="divide-y divide-white/5">
            {sorted.map((job) => (
              <JobRow
                key={job.jobId}
                job={job}
                now={now}
                personaName={
                  job.personaId
                    ? personas.find((p) => p.id === job.personaId)?.name ?? null
                    : null
                }
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
