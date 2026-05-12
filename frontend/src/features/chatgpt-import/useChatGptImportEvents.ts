/**
 * Subscribe the ChatGPT-import store to backend WebSocket events.
 *
 * Listens on the ``chatgpt_import.*`` namespace via the shared event bus.
 * The hook is mounted once by ``ChatGptImportTab``; unsubscribes on unmount.
 */
import { useEffect } from 'react'

import { eventBus } from '../../core/websocket/eventBus'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

export function useChatGptImportEvents(): void {
  useEffect(() => {
    const unsub = eventBus.on('chatgpt_import.*', (event) => {
      const p = event.payload as Record<string, unknown>
      const store = useChatGptImportStore.getState()
      const active = store.activeImport
      // All events carry an import_id; ignore events that target a different
      // import than the one currently displayed in this tab.
      const eventImportId = p.import_id as string | undefined
      if (active && eventImportId && eventImportId !== active.import_id) return

      switch (event.type) {
        case 'chatgpt_import.parse.started': {
          store.setParseProgress({ conversationsIndexed: 0 })
          break
        }
        case 'chatgpt_import.parse.progress': {
          store.setParseProgress({
            conversationsIndexed: (p.conversations_indexed as number) ?? 0,
          })
          break
        }
        case 'chatgpt_import.parse.done': {
          store.setParseProgress(null)
          if (active) {
            store.setActiveImport({
              ...active,
              status: 'ready',
              conversation_count: (p.conversation_count as number) ?? 0,
              skipped_count: (p.skipped_count as number) ?? 0,
              skipped_reasons:
                (p.skipped_reasons as Record<string, number>) ?? {},
              expires_at: (p.expires_at as string) ?? active.expires_at,
            })
          }
          break
        }
        case 'chatgpt_import.parse.failed': {
          store.setParseProgress(null)
          if (active) {
            store.setActiveImport({
              ...active,
              status: 'failed',
              error_message: (p.error_message as string) ?? 'Unknown error',
            })
          }
          break
        }
        case 'chatgpt_import.conversation.imported': {
          const convId = p.chatgpt_conversation_id as string
          store.markConversationImported(convId, {
            persona_id: p.persona_id as string,
            // Resolved in the row UI from the in-page persona list; the
            // event payload doesn't carry the name.
            persona_name: '',
            session_id: p.session_id as string,
            imported_at: new Date().toISOString(),
          })
          break
        }
        case 'chatgpt_import.conversation.import_failed': {
          store.markConversationImportFailed(p.chatgpt_conversation_id as string)
          break
        }
      }
    })
    return unsub
  }, [])
}
