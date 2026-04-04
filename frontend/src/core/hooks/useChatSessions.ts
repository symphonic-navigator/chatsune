import { useCallback, useEffect, useState } from "react"
import { chatApi, type ChatSessionDto } from "../api/chat"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { BaseEvent } from "../types/events"

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSessionDto[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await chatApi.listSessions()
      setSessions(res.sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
    } catch {
      // Empty history is acceptable — API may not have sessions yet
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()
  }, [fetch])

  // Subscribe to session lifecycle events
  useEffect(() => {
    const unsubCreated = eventBus.on(Topics.CHAT_SESSION_CREATED, (event: BaseEvent) => {
      const p = event.payload
      const newSession: ChatSessionDto = {
        id: p.session_id as string,
        user_id: p.user_id as string,
        persona_id: p.persona_id as string,
        model_unique_id: p.model_unique_id as string,
        state: "idle",
        title: (p.title as string) ?? null,
        created_at: p.created_at as string,
        updated_at: p.updated_at as string,
      }
      setSessions((prev) => [newSession, ...prev])
    })

    const unsubDeleted = eventBus.on(Topics.CHAT_SESSION_DELETED, (event: BaseEvent) => {
      const sessionId = event.payload.session_id as string
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
    })

    const unsubTitle = eventBus.on(Topics.CHAT_SESSION_TITLE_UPDATED, (event: BaseEvent) => {
      const sessionId = event.payload.session_id as string
      const title = event.payload.title as string
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, title } : s)),
      )
    })

    return () => {
      unsubCreated()
      unsubDeleted()
      unsubTitle()
    }
  }, [])

  return { sessions, isLoading, refetch: fetch }
}
