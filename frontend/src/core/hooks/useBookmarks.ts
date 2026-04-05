import { useCallback, useEffect, useState } from "react"
import { bookmarksApi } from "../api/bookmarks"
import type { BookmarkDto } from "../types/bookmark"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { BaseEvent } from "../types/events"

export function useBookmarks(sessionId?: string) {
  const [bookmarks, setBookmarks] = useState<BookmarkDto[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await bookmarksApi.list(sessionId)
      setBookmarks(res)
    } catch {
      // Non-critical
    } finally {
      setIsLoading(false)
    }
  }, [sessionId])

  useEffect(() => { fetch() }, [fetch])

  useEffect(() => {
    const unsubCreated = eventBus.on(Topics.BOOKMARK_CREATED, (event: BaseEvent) => {
      const bm = event.payload.bookmark as unknown as BookmarkDto
      if (!bm) return
      // If we're filtering by session, only add if it matches
      if (sessionId && bm.session_id !== sessionId) return
      setBookmarks((prev) => prev.some((b) => b.id === bm.id) ? prev : [bm, ...prev])
    })

    const unsubUpdated = eventBus.on(Topics.BOOKMARK_UPDATED, (event: BaseEvent) => {
      const bm = event.payload.bookmark as unknown as BookmarkDto
      if (!bm) return
      setBookmarks((prev) => prev.map((b) => b.id === bm.id ? bm : b))
    })

    const unsubDeleted = eventBus.on(Topics.BOOKMARK_DELETED, (event: BaseEvent) => {
      const bmId = event.payload.bookmark_id as string
      setBookmarks((prev) => prev.filter((b) => b.id !== bmId))
    })

    return () => { unsubCreated(); unsubUpdated(); unsubDeleted() }
  }, [sessionId])

  const addBookmark = useCallback((bm: BookmarkDto) => {
    setBookmarks((prev) => prev.some((b) => b.id === bm.id) ? prev : [bm, ...prev])
  }, [])

  const removeBookmark = useCallback((bookmarkId: string) => {
    setBookmarks((prev) => prev.filter((b) => b.id !== bookmarkId))
  }, [])

  return { bookmarks, setBookmarks, isLoading, refetch: fetch, addBookmark, removeBookmark }
}
