import { create } from 'zustand'
import { chatApi } from '@/core/api/chat'

type CockpitSessionState = {
  thinking: boolean
  tools: boolean
  autoRead: boolean
}

type CockpitStoreShape = {
  bySession: Record<string, CockpitSessionState>
  hydrateFromServer: (
    sessionId: string,
    state: CockpitSessionState,
  ) => void
  setThinking: (sessionId: string, value: boolean) => Promise<void>
  setTools: (sessionId: string, value: boolean) => Promise<void>
  setAutoRead: (sessionId: string, value: boolean) => Promise<void>
}

export const useCockpitStore = create<CockpitStoreShape>((set, get) => ({
  bySession: {},

  hydrateFromServer: (sessionId, state) =>
    set((s) => ({
      bySession: { ...s.bySession, [sessionId]: state },
    })),

  setThinking: async (sessionId, value) => {
    const prev = get().bySession[sessionId]
    if (!prev) return
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, thinking: value },
      },
    }))
    try {
      await chatApi.updateSessionReasoning(sessionId, value ? true : null)
    } catch (e) {
      set((s) => ({
        bySession: { ...s.bySession, [sessionId]: prev },
      }))
      throw e
    }
  },

  setTools: async (sessionId, value) => {
    const prev = get().bySession[sessionId]
    if (!prev) return
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, tools: value },
      },
    }))
    try {
      await chatApi.updateSessionToggles(sessionId, { tools_enabled: value })
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

export function useCockpitSession(sessionId: string | null): CockpitSessionState | null {
  return useCockpitStore((s) => (sessionId ? s.bySession[sessionId] ?? null : null))
}
