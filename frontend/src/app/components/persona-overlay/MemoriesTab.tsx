import { useEffect, useState } from 'react'
import { useMemoryStore } from '../../../core/store/memoryStore'
import { memoryApi } from '../../../core/api/memory'
import { useMemoryEvents } from '../../../features/memory/useMemoryEvents'
import type { JournalEntryDto } from '../../../core/api/memory'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import UncommittedSection from '../../../features/memory/UncommittedSection'
import CommittedSection from '../../../features/memory/CommittedSection'
import MemoryBodySection from '../../../features/memory/MemoryBodySection'

const EMPTY_ENTRIES: JournalEntryDto[] = []

interface MemoriesTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function MemoriesTab({ persona, chakra: _chakra }: MemoriesTabProps) {
  const personaId = persona.id
  const [dreamBusy, setDreamBusy] = useState(false)
  const [extractBusy, setExtractBusy] = useState(false)
  const isExtracting = useMemoryStore((s) => s.isExtracting[personaId] ?? false)

  const uncommittedEntries = useMemoryStore((s) =>
    s.uncommittedEntries[personaId] ?? EMPTY_ENTRIES
  )
  const committedEntries = useMemoryStore((s) =>
    s.committedEntries[personaId] ?? EMPTY_ENTRIES
  )
  const isDreaming = useMemoryStore((s) => s.isDreaming[personaId] ?? false)
  const setUncommittedEntries = useMemoryStore((s) => s.setUncommittedEntries)
  const setCommittedEntries = useMemoryStore((s) => s.setCommittedEntries)
  const resetToastCounter = useMemoryStore((s) => s.resetToastCounter)

  useMemoryEvents(personaId)

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
        // Leave store state as-is on error
      }
    }

    load()
    return () => { cancelled = true }
  }, [personaId, setUncommittedEntries, setCommittedEntries, resetToastCounter])

  const dreamDisabled = dreamBusy || isDreaming || committedEntries.length === 0

  const handleDream = async () => {
    if (dreamDisabled) return
    setDreamBusy(true)
    try {
      await memoryApi.triggerDream(personaId)
    } finally {
      setDreamBusy(false)
    }
  }

  const handleExtract = async () => {
    if (extractBusy || isExtracting) return
    setExtractBusy(true)
    try {
      await memoryApi.triggerExtraction(personaId, true)
    } finally {
      setExtractBusy(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-8">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-white/60">Memories</span>
          {isDreaming && (
            <span className="flex items-center gap-1.5 text-[11px] text-purple-400">
              <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Dreaming...
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExtract}
            disabled={extractBusy || isExtracting}
            className="px-3 py-1.5 rounded-md text-xs bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title="Extract memories from recent chat messages"
          >
            {isExtracting ? 'Extracting...' : 'Extract Now'}
          </button>
          <button
            onClick={handleDream}
            disabled={dreamDisabled}
            className="px-3 py-1.5 rounded-md text-xs bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title={committedEntries.length === 0 ? 'No committed entries to consolidate' : 'Consolidate committed entries into memory body'}
          >
            Dream Now
          </button>
        </div>
      </div>

      <UncommittedSection personaId={personaId} entries={uncommittedEntries} />
      <CommittedSection personaId={personaId} entries={committedEntries} />
      <MemoryBodySection personaId={personaId} />
    </div>
  )
}
