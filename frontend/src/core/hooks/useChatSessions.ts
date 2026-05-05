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
      const projectId = (p.project_id as string | null | undefined) ?? null
      // Mindspace: this hook represents global, non-project history.
      // Project-bound sessions are loaded by the project-detail-overlay's
      // own scoped fetch and must not enter this list.
      if (projectId !== null) return
      const newSession: ChatSessionDto = {
        id: p.session_id as string,
        user_id: p.user_id as string,
        persona_id: p.persona_id as string,
        state: "idle",
        title: (p.title as string) ?? null,
        tools_enabled: false,
        auto_read: false,
        reasoning_override: null,
        pinned: false,
        project_id: null,
        created_at: p.created_at as string,
        updated_at: p.updated_at as string,
      }
      setSessions((prev) =>
        prev.some((s) => s.id === newSession.id) ? prev : [newSession, ...prev],
      )
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

    const unsubPinned = eventBus.on(Topics.CHAT_SESSION_PINNED_UPDATED, (event: BaseEvent) => {
      const sessionId = event.payload.session_id as string
      const pinned = event.payload.pinned as boolean
      // Backend's update_session_pinned bumps updated_at server-side so the
      // freshly-pinned session surfaces at the top of its group. The pin
      // event payload doesn't echo the new timestamp, so mirror it locally
      // using the event's own timestamp — otherwise the sidebar sort by
      // updated_at would keep the session at its stale position.
      const ts = (event.timestamp ?? new Date().toISOString()) as string
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, pinned, updated_at: ts } : s)),
      )
    })

    const unsubRestored = eventBus.on(Topics.CHAT_SESSION_RESTORED, (event: BaseEvent) => {
      const session = event.payload.session as ChatSessionDto
      if (!session) return
      setSessions((prev) =>
        prev.some((s) => s.id === session.id)
          ? prev
          : [...prev, session].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      )
    })

    // Mindspace: a session was assigned to (or detached from) a project.
    // This hook represents global, non-project history, so membership
    // changes are add/remove operations rather than an in-place patch:
    //   - Assigned to a project (project_id !== null) → drop from this list.
    //   - Detached (project_id === null) → fetch the session and prepend
    //     it, so it surfaces in the sidebar / global HistoryTab without a
    //     full refetch.
    const unsubProject = eventBus.on(
      Topics.CHAT_SESSION_PROJECT_UPDATED,
      (event: BaseEvent) => {
        const sessionId = event.payload.session_id as string
        const projectId = (event.payload.project_id as string | null | undefined) ?? null
        if (projectId !== null) {
          setSessions((prev) => prev.filter((s) => s.id !== sessionId))
          return
        }
        // Detached → pull the session and prepend it. Failures are
        // swallowed silently, mirroring the initial fetch above.
        chatApi.getSession(sessionId).then((fetched) => {
          setSessions((prev) =>
            prev.some((s) => s.id === fetched.id) ? prev : [fetched, ...prev],
          )
        }).catch(() => {
          // Ignore — empty/unreachable history is acceptable here.
        })
      },
    )

    return () => {
      unsubCreated()
      unsubDeleted()
      unsubTitle()
      unsubPinned()
      unsubRestored()
      unsubProject()
    }
  }, [])

  const updateSession = useCallback((sessionId: string, patch: Partial<ChatSessionDto>) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, ...patch } : s)),
    )
  }, [])

  return { sessions, isLoading, refetch: fetch, updateSession }
}
