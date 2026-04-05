export interface BookmarkDto {
  id: string
  user_id: string
  session_id: string
  message_id: string
  persona_id: string
  title: string
  scope: "global" | "local"
  display_order: number
  created_at: string
}

export interface CreateBookmarkRequest {
  session_id: string
  message_id: string
  persona_id: string
  title: string
  scope: "global" | "local"
}

export interface UpdateBookmarkRequest {
  title?: string
  scope?: "global" | "local"
}
