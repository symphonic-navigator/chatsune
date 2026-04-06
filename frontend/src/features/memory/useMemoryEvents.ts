import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useMemoryStore } from '../../core/store/memoryStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import type { JournalEntryDto } from '../../core/api/memory'

const TOAST_THRESHOLD = 50

// Module-level dedup: prevents duplicate toasts when multiple useMemoryEvents
// hooks are active simultaneously (e.g. ChatView + MemoriesTab).
const _toastedCorrelations = new Set<string>()

export function useMemoryEvents(personaId: string | null) {
  useEffect(() => {
    if (!personaId) return

    const store = useMemoryStore.getState
    const notify = useNotificationStore.getState

    const handleEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>
      const eventPersonaId = p.persona_id as string | undefined

      // Only handle events for the active persona
      if (eventPersonaId && eventPersonaId !== personaId) return

      switch (event.type) {
        case Topics.MEMORY_ENTRY_CREATED: {
          const entry = p.entry as JournalEntryDto
          store().addEntry(personaId, entry)
          const counter = store().toastCounter[personaId] ?? 0
          if (counter > 0 && counter % TOAST_THRESHOLD === 0) {
            notify().addNotification({
              level: 'info',
              title: 'Memory entries accumulating',
              message: `${counter} uncommitted memory entries for this persona. Open the Memories tab to review.`,
            })
          }
          break
        }
        case Topics.MEMORY_ENTRY_COMMITTED: {
          const entry = p.entry as JournalEntryDto
          store().commitEntry(personaId, entry)
          break
        }
        case Topics.MEMORY_ENTRY_UPDATED: {
          const entry = p.entry as JournalEntryDto
          store().updateEntry(personaId, entry)
          break
        }
        case Topics.MEMORY_ENTRY_DELETED: {
          const entryId = p.entry_id as string
          store().removeEntry(personaId, entryId)
          break
        }
        case Topics.MEMORY_ENTRY_AUTO_COMMITTED: {
          const entry = p.entry as JournalEntryDto
          store().autoCommitEntry(personaId, entry)
          break
        }
        case Topics.MEMORY_DREAM_STARTED: {
          store().setDreaming(personaId, true)
          break
        }
        case Topics.MEMORY_DREAM_COMPLETED: {
          store().setDreaming(personaId, false)
          store().setCommittedEntries(personaId, [])
          if (!_toastedCorrelations.has(event.correlation_id)) {
            _toastedCorrelations.add(event.correlation_id)
            notify().addNotification({
              level: 'success',
              title: 'Dream completed',
              message: 'Memory consolidation finished successfully.',
            })
          }
          break
        }
        case Topics.MEMORY_DREAM_FAILED: {
          store().setDreaming(personaId, false)
          if (!_toastedCorrelations.has(event.correlation_id)) {
            _toastedCorrelations.add(event.correlation_id)
            notify().addNotification({
              level: 'error',
              title: 'Dream failed',
              message: (p.error as string | undefined) ?? 'Memory consolidation encountered an error.',
            })
          }
          break
        }
        case Topics.MEMORY_EXTRACTION_STARTED: {
          store().setExtracting(personaId, true)
          break
        }
        case Topics.MEMORY_EXTRACTION_COMPLETED: {
          store().setExtracting(personaId, false)
          break
        }
        case Topics.MEMORY_EXTRACTION_FAILED: {
          store().setExtracting(personaId, false)
          break
        }
        case Topics.MEMORY_BODY_ROLLBACK: {
          if (!_toastedCorrelations.has(event.correlation_id)) {
            _toastedCorrelations.add(event.correlation_id)
            notify().addNotification({
              level: 'info',
              title: 'Memory rolled back',
              message: `Memory body restored to version ${p.rolled_back_to_version as number ?? 'previous'}.`,
            })
          }
          break
        }
      }
    }

    const unsub = eventBus.on('memory.*', handleEvent)
    return unsub
  }, [personaId])
}
