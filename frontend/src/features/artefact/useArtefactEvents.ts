import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useArtefactStore } from '../../core/store/artefactStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import type { ArtefactType } from '../../core/types/artefact'

export function useArtefactEvents(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    const store = useArtefactStore.getState

    const handleEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>
      if (p.session_id !== sessionId) return

      switch (event.type) {
        case Topics.ARTEFACT_CREATED: {
          store().addArtefact({
            id: (p.artefact_id as string) ?? '',
            session_id: sessionId,
            handle: p.handle as string,
            title: p.title as string,
            type: p.artefact_type as ArtefactType,
            language: (p.language as string) ?? null,
            size_bytes: p.size_bytes as number,
            version: 1,
            created_at: event.timestamp,
            updated_at: event.timestamp,
          })
          if (store().artefacts.length <= 1) {
            store().setSidebarOpen(true)
          }
          break
        }
        case Topics.ARTEFACT_UPDATED: {
          store().updateArtefact(p.handle as string, {
            title: p.title as string,
            size_bytes: p.size_bytes as number,
            version: p.version as number,
            updated_at: event.timestamp,
          })
          const active = store().activeArtefact
          if (active && active.handle === p.handle) {
            store().setActiveArtefact(null)
            store().setActiveArtefactLoading(true)
          }
          break
        }
        case Topics.ARTEFACT_DELETED: {
          store().removeArtefact(p.handle as string)
          break
        }
        case Topics.ARTEFACT_UNDO:
        case Topics.ARTEFACT_REDO: {
          store().updateArtefact(p.handle as string, {
            version: p.version as number,
            updated_at: event.timestamp,
          })
          const active = store().activeArtefact
          if (active && active.handle === p.handle) {
            store().setActiveArtefact(null)
            store().setActiveArtefactLoading(true)
          }
          break
        }
      }
    }

    const unsub = eventBus.on('artefact.*', handleEvent)
    return unsub
  }, [sessionId])
}
