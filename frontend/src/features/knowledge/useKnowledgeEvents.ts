import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useKnowledgeStore } from '../../core/store/knowledgeStore'
import { useChatStore } from '../../core/store/chatStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import type { KnowledgeLibraryDto, KnowledgeDocumentDto, RetrievedChunkDto } from '../../core/types/knowledge'

export function useKnowledgeEvents() {
  useEffect(() => {
    const knowledgeStore = useKnowledgeStore.getState
    const chatStore = useChatStore.getState
    const notify = useNotificationStore.getState

    const handleEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>

      switch (event.type) {
        case Topics.KNOWLEDGE_LIBRARY_CREATED:
          knowledgeStore().onLibraryCreated(p.library as KnowledgeLibraryDto)
          break

        case Topics.KNOWLEDGE_LIBRARY_UPDATED:
          knowledgeStore().onLibraryUpdated(p.library as KnowledgeLibraryDto)
          break

        case Topics.KNOWLEDGE_LIBRARY_DELETED:
          knowledgeStore().onLibraryDeleted(p.library_id as string)
          break

        case Topics.KNOWLEDGE_DOCUMENT_CREATED:
          knowledgeStore().onDocumentCreated(p.document as KnowledgeDocumentDto)
          break

        case Topics.KNOWLEDGE_DOCUMENT_UPDATED:
          knowledgeStore().onDocumentUpdated(p.document as KnowledgeDocumentDto)
          break

        case Topics.KNOWLEDGE_DOCUMENT_DELETED:
          knowledgeStore().onDocumentDeleted(p.library_id as string, p.document_id as string)
          break

        case Topics.KNOWLEDGE_DOCUMENT_EMBEDDING:
          knowledgeStore().onDocumentEmbeddingStatus(p.document_id as string, 'processing')
          break

        case Topics.KNOWLEDGE_DOCUMENT_EMBEDDED:
          knowledgeStore().onDocumentEmbeddingStatus(p.document_id as string, 'completed')
          break

        case Topics.KNOWLEDGE_DOCUMENT_EMBED_FAILED: {
          const error = p.error as string | undefined
          knowledgeStore().onDocumentEmbeddingStatus(p.document_id as string, 'failed', error)
          if (!(p.recoverable as boolean)) {
            notify().addNotification({
              level: 'error',
              title: 'Embedding failed',
              message: error ?? 'A document could not be embedded.',
            })
          }
          break
        }

        case Topics.KNOWLEDGE_SEARCH_COMPLETED:
          chatStore().setStreamingKnowledgeContext(p.results as RetrievedChunkDto[])
          break
      }
    }

    const unsub = eventBus.on('knowledge.*', handleEvent)
    return unsub
  }, [])
}
