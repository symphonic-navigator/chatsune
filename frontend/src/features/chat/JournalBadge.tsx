import { useEffect, useRef, useState } from 'react'
import { memoryApi } from '../../core/api/memory'
import { useMemoryStore } from '../../core/store/memoryStore'
import { JournalDropdown } from './JournalDropdown'

interface JournalBadgeProps {
  personaId: string
}

function badgeColour(count: number): string {
  if (count <= 20) return 'bg-green-500'
  if (count <= 35) return 'bg-yellow-400'
  return 'bg-red-500'
}

function badgeBorderColour(count: number): string {
  if (count <= 20) return 'border-green-500/20'
  if (count <= 35) return 'border-yellow-400/20'
  return 'border-red-500/20'
}

function badgeTextColour(count: number): string {
  if (count <= 20) return 'text-green-400'
  if (count <= 35) return 'text-yellow-300'
  return 'text-red-400'
}

export function JournalBadge({ personaId }: JournalBadgeProps) {
  const [open, setOpen] = useState(false)
  const [isPulsing, setIsPulsing] = useState(false)
  const pulseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevCountRef = useRef<number>(0)

  const entries = useMemoryStore((s) => s.uncommittedEntries[personaId] ?? [])
  const context = useMemoryStore((s) => s.context[personaId] ?? null)
  const store = useMemoryStore.getState

  // Fetch initial data on mount
  useEffect(() => {
    memoryApi.getContext(personaId)
      .then((ctx) => store().setContext(personaId, ctx))
      .catch(() => {})

    memoryApi.listJournalEntries(personaId, 'uncommitted')
      .then((list) => store().setUncommittedEntries(personaId, list))
      .catch(() => {})
  }, [personaId, store])

  // Trigger pulse animation when new entries arrive
  useEffect(() => {
    const count = entries.length
    if (count > prevCountRef.current) {
      setIsPulsing(true)
      if (pulseTimeoutRef.current) clearTimeout(pulseTimeoutRef.current)
      // ~3 pulses at 1s each
      pulseTimeoutRef.current = setTimeout(() => setIsPulsing(false), 3000)
    }
    prevCountRef.current = count
  }, [entries.length])

  useEffect(() => {
    return () => {
      if (pulseTimeoutRef.current) clearTimeout(pulseTimeoutRef.current)
    }
  }, [])

  const count = entries.length
  if (count === 0) return null

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] transition-colors ${badgeBorderColour(count)} bg-white/3 ${badgeTextColour(count)} hover:bg-white/5`}
        title={`${count} uncommitted journal entries`}
      >
        <span
          className={`h-1.5 w-1.5 rounded-full ${badgeColour(count)} ${isPulsing ? 'animate-pulse' : ''}`}
        />
        <span>MEM {count}</span>
      </button>

      {open && (
        <JournalDropdown
          personaId={personaId}
          entries={entries}
          canTriggerExtraction={context?.can_trigger_extraction ?? false}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  )
}
