import { useMemo } from 'react'
import { create } from 'zustand'
import { chatApi, type ChatSessionExtras } from '@/core/api/chat'
import { eventBus } from '@/core/websocket/eventBus'
import { Topics, type BaseEvent } from '@/core/types/events'

/**
 * Per-session cockpit state. ``extras`` carries the capability-aware
 * reasoning/tools settings (mirroring the backend ``ChatSessionExtras``);
 * ``autoRead`` lives alongside as an unrelated playback preference.
 */
export type CockpitSessionState = {
  extras: ChatSessionExtras
  autoRead: boolean
}

/**
 * Read-side view returned by ``useCockpitSession``. Exposes the canonical
 * ``extras`` shape plus a flat ``tools`` alias used by readers (ImageButton,
 * CockpitBar's MobileInfoModal, IntegrationsButton derivations) that only
 * care whether tools are on, not about the rest of the extras. Writes go
 * through ``updateExtras`` — there is no shim writer.
 */
export type CockpitSessionView = CockpitSessionState & {
  /** Convenience alias for ``extras.tools_enabled``. Read-only. */
  tools: boolean
}

type CockpitStoreShape = {
  bySession: Record<string, CockpitSessionState>
  /**
   * Message id for which the cockpit requests auto-read playback. The
   * parent (AssistantMessage) writes this on the streaming→done transition
   * when auto-read is on; the ReadAloudButton reads it, fires playback,
   * and clears it. Single slot — only the most recent completion drives it.
   */
  pendingAutoReadMessageId: string | null
  hydrateFromServer: (sessionId: string, state: CockpitSessionState) => void
  /**
   * Replace the ``extras`` slice of an already-hydrated session. Used by
   * the ``chat.session.extras.updated`` WS subscription so that other tabs
   * see live changes without a follow-up REST call. Sessions that haven't
   * been hydrated yet are ignored — the next ``getSession`` will pick up
   * the latest server state.
   */
  hydrateExtras: (sessionId: string, extras: ChatSessionExtras) => void
  /**
   * Patch a subset of ``extras`` and PATCH the server. Optimistic: the
   * local state updates immediately and rolls back if the server rejects
   * the new shape (capability validation in the PATCH endpoint).
   */
  updateExtras: (
    sessionId: string,
    patch: Partial<ChatSessionExtras>,
  ) => Promise<void>
  setAutoRead: (sessionId: string, value: boolean) => Promise<void>
  requestAutoRead: (messageId: string) => void
  clearAutoReadRequest: () => void
}

export const useCockpitStore = create<CockpitStoreShape>((set, get) => ({
  bySession: {},
  pendingAutoReadMessageId: null,

  hydrateFromServer: (sessionId, state) =>
    set((s) => ({
      bySession: { ...s.bySession, [sessionId]: state },
    })),

  hydrateExtras: (sessionId, extras) =>
    set((s) => {
      const prev = s.bySession[sessionId]
      if (!prev) return s
      return {
        bySession: {
          ...s.bySession,
          [sessionId]: { ...prev, extras },
        },
      }
    }),

  requestAutoRead: (messageId) => set({ pendingAutoReadMessageId: messageId }),
  clearAutoReadRequest: () => set({ pendingAutoReadMessageId: null }),

  updateExtras: async (sessionId, patch) => {
    const prev = get().bySession[sessionId]
    if (!prev) return
    const next: ChatSessionExtras = { ...prev.extras, ...patch }
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, extras: next },
      },
    }))
    try {
      await chatApi.updateSessionExtras(sessionId, next)
    } catch (e) {
      set((s) => ({
        bySession: { ...s.bySession, [sessionId]: prev },
      }))
      throw e
    }
  },

  setAutoRead: async (sessionId, value) => {
    const prev = get().bySession[sessionId]
    if (!prev) return
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, autoRead: value },
      },
    }))
    try {
      await chatApi.updateSessionToggles(sessionId, { auto_read: value })
    } catch (e) {
      set((s) => ({
        bySession: { ...s.bySession, [sessionId]: prev },
      }))
      throw e
    }
  },
}))

/**
 * Hook accessor returning a session's cockpit state plus the legacy flat
 * aliases. Returns ``null`` for unknown sessions so callers can render an
 * "unhydrated" placeholder.
 *
 * Subscribes to the entry reference directly (reference-stable across
 * unrelated store updates) and derives the view object via ``useMemo``.
 * Returning a freshly-constructed object from the selector itself triggers
 * useSyncExternalStore's "getSnapshot should be cached" infinite-loop
 * guard, so we keep the selector cheap and stable.
 */
export function useCockpitSession(
  sessionId: string | null,
): CockpitSessionView | null {
  const entry = useCockpitStore((s) =>
    sessionId ? s.bySession[sessionId] ?? null : null,
  )
  return useMemo(() => {
    if (!entry) return null
    return {
      extras: entry.extras,
      autoRead: entry.autoRead,
      tools: entry.extras.tools_enabled,
    }
  }, [entry])
}

// Multi-tab/device sync — when another tab PATCHes the session extras the
// backend broadcasts ``chat.session.extras.updated`` on the session scope.
// Hydrate the local store from the event payload so the cockpit reflects
// the change without a follow-up REST call. Sessions that haven't been
// hydrated locally yet are ignored (handled by ``hydrateExtras``).
//
// Module-level subscription mirrors ``useProjectsStore`` — registers once
// at app boot, no React hook plumbing required because the cockpit store is
// a singleton. The handler is defensive about payload shape: if the event
// arrives malformed we drop it silently rather than corrupt state.
eventBus.on(Topics.CHAT_SESSION_EXTRAS_UPDATED, (event: BaseEvent) => {
  const payload = event.payload as {
    session_id?: unknown
    extras?: unknown
  }
  if (typeof payload.session_id !== 'string' || !payload.extras) return
  const raw = payload.extras as Partial<ChatSessionExtras>
  if (
    typeof raw.tools_enabled !== 'boolean' ||
    (raw.reasoning_mode !== 'on' && raw.reasoning_mode !== 'off')
  ) {
    return
  }
  const extras: ChatSessionExtras = {
    tools_enabled: raw.tools_enabled,
    reasoning_mode: raw.reasoning_mode,
    reasoning_effort:
      typeof raw.reasoning_effort === 'string' ? raw.reasoning_effort : null,
  }
  useCockpitStore.getState().hydrateExtras(payload.session_id, extras)
})
