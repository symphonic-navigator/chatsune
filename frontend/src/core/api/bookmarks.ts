import { api } from "./client"
import type { BookmarkDto, CreateBookmarkRequest, UpdateBookmarkRequest } from "../types/bookmark"

export const bookmarksApi = {
  create: (data: CreateBookmarkRequest) =>
    api.post<BookmarkDto>("/api/bookmarks", data),

  list: (sessionId?: string) => {
    const qs = sessionId ? `?session_id=${sessionId}` : ""
    return api.get<BookmarkDto[]>(`/api/bookmarks${qs}`)
  },

  update: (bookmarkId: string, data: UpdateBookmarkRequest) =>
    api.patch<BookmarkDto>(`/api/bookmarks/${bookmarkId}`, data),

  remove: (bookmarkId: string) =>
    api.delete<{ status: string }>(`/api/bookmarks/${bookmarkId}`),

  reorder: (orderedIds: string[]) =>
    api.patch<{ status: string }>("/api/bookmarks/reorder", { ordered_ids: orderedIds }),
}
