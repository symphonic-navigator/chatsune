import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMemoryStore } from '../../core/store/memoryStore'
import { memoryApi } from '../../core/api/memory'
import { useMemoryEvents } from './useMemoryEvents'
import UncommittedSection from './UncommittedSection'
import CommittedSection from './CommittedSection'
import MemoryBodySection from './MemoryBodySection'

export default function MemoryPage() {
  const { personaId } = useParams<{ personaId: string }>()
  const navigate = useNavigate()

  const uncommittedEntries = useMemoryStore((s) =>
    personaId ? (s.uncommittedEntries[personaId] ?? []) : []
  )
  const committedEntries = useMemoryStore((s) =>
    personaId ? (s.committedEntries[personaId] ?? []) : []
  )
  const setUncommittedEntries = useMemoryStore((s) => s.setUncommittedEntries)
  const setCommittedEntries = useMemoryStore((s) => s.setCommittedEntries)
  const resetToastCounter = useMemoryStore((s) => s.resetToastCounter)

  useMemoryEvents(personaId ?? null)

  useEffect(() => {
    if (!personaId) return
    resetToastCounter(personaId)

    let cancelled = false

    const load = async () => {
      try {
        const [uncommitted, committed] = await Promise.all([
          memoryApi.listJournalEntries(personaId, 'uncommitted'),
          memoryApi.listJournalEntries(personaId, 'committed'),
        ])
        if (!cancelled) {
          setUncommittedEntries(personaId, uncommitted)
          setCommittedEntries(personaId, committed)
        }
      } catch {
        // leave store state as-is on error
      }
    }

    load()
    return () => { cancelled = true }
  }, [personaId, setUncommittedEntries, setCommittedEntries, resetToastCounter])

  if (!personaId) {
    return (
      <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
        No persona selected
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-8">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-1.5 text-xs text-white/40 hover:text-white/60 transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 5l-7 7 7 7" />
            </svg>
            Back
          </button>
          <h1 className="text-base text-white/60 font-medium">Memory</h1>
        </div>

        <UncommittedSection personaId={personaId} entries={uncommittedEntries} />
        <CommittedSection personaId={personaId} entries={committedEntries} />
        <MemoryBodySection personaId={personaId} />
      </div>
    </div>
  )
}
