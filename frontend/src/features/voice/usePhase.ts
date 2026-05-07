/**
 * usePhase — thin React hook that derives the conversation phase from the
 * per-session Group registry (pub-sub) and the conversation-mode store.
 *
 * See devdocs/voice-barge-structural-redesign.md §4. This hook replaces the
 * scattered `setPhase` effects once all call sites have migrated; for now
 * it runs alongside the legacy `phase` field in conversationModeStore.
 *
 * The hook subscribes to two reactive sources:
 *   1. Per-session Group pub-sub via useSyncExternalStore, filtered to the
 *      currently active chat session.
 *   2. conversationModeStore (five fields) via zustand's selector.
 *
 * useSyncExternalStore expects a listener with no arguments; the registry
 * emits `(sessionId, group)`. The tiny adaptor below discards both —
 * useSyncExternalStore re-reads the snapshot on every notification anyway,
 * and the snapshot itself filters by the active session id.
 *
 * The snapshot is built as a stable string `"<groupId>:<groupState>"` so
 * React's Object.is check on the snapshot catches a state-only change
 * (where the Group reference is stable but its `.state` field has moved).
 * We still read getActiveGroupForSession() directly for the Group itself —
 * the snapshot's only job is to gate re-renders.
 */

import { useSyncExternalStore } from 'react'
import {
  subscribeGroups,
  getActiveGroupForSession,
} from '../chat/responseTaskGroup'
import { useConversationModeStore } from './stores/conversationModeStore'
import { useChatStore } from '../../core/store/chatStore'
import { derivePhase } from './derivePhase'
import type { ConversationPhase } from './stores/conversationModeStore'

function subscribeActiveGroupForRsx(onStoreChange: () => void): () => void {
  return subscribeGroups((sid) => {
    const activeSid = useChatStore.getState().activeSessionId
    if (sid === activeSid) onStoreChange()
  })
}

function activeGroupSnapshot(): string {
  const activeSid = useChatStore.getState().activeSessionId
  if (!activeSid) return 'none'
  const g = getActiveGroupForSession(activeSid)
  return g === null ? 'none' : `${g.id}:${g.state}`
}

function serverSnapshot(): string {
  return 'none'
}

export function usePhase(): ConversationPhase {
  // We subscribe purely to force re-renders on active-Group state changes;
  // the snapshot value itself is discarded — derivePhase reads the live
  // Group via getActiveGroupForSession() below.
  useSyncExternalStore(
    subscribeActiveGroupForRsx,
    activeGroupSnapshot,
    serverSnapshot,
  )
  const activeSessionId = useChatStore((s) => s.activeSessionId)
  const activeGroup = activeSessionId
    ? getActiveGroupForSession(activeSessionId)
    : null

  const active = useConversationModeStore((s) => s.active)
  const isHolding = useConversationModeStore((s) => s.isHolding)
  const currentBargeState = useConversationModeStore((s) => s.currentBargeState)
  const sttInFlight = useConversationModeStore((s) => s.sttInFlight)
  const vadActive = useConversationModeStore((s) => s.vadActive)

  return derivePhase({
    active,
    isHolding,
    vadActive,
    bargeState: currentBargeState,
    sttInFlight,
    groupState: activeGroup?.state ?? null,
  })
}
