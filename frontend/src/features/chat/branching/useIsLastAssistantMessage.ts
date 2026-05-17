import { useMemo } from 'react'
import type { ChatMessageDto } from '../../../core/api/chat'

/**
 * True when ``messageId`` is the most recent ``assistant`` message in
 * ``messages`` (chronological tail). Used by ``MessageList`` to decide
 * whether the Regenerate button keeps its "Regenerate" label (in-place
 * rewrite on the same session) or flips to "Branch & Regenerate" (forks
 * to a new branch first). See
 * ``devdocs/specs/2026-05-17-branching-design.md`` §6.1.
 */
export function useIsLastAssistantMessage(
  messageId: string,
  messages: readonly ChatMessageDto[],
): boolean {
  return useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') {
        return messages[i].id === messageId
      }
    }
    return false
  }, [messageId, messages])
}
