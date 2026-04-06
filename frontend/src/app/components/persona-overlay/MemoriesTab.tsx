import { useEffect } from 'react'
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

  const uncommittedEntries = useMemoryStore((s) =>
    s.uncommittedEntries[personaId] ?? EMPTY_ENTRIES
  )
  const committedEntries = useMemoryStore((s) =>
    s.committedEntries[personaId] ?? EMPTY_ENTRIES
  )
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

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-8">
      <UncommittedSection personaId={personaId} entries={uncommittedEntries} />
      <CommittedSection personaId={personaId} entries={committedEntries} />
      <MemoryBodySection personaId={personaId} />
    </div>
  )
}
