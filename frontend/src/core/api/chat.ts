import { api } from "./client"

interface ChatSessionDto {
  id: string
  user_id: string
  persona_id: string
  model_unique_id: string
  state: "idle" | "streaming" | "requires_action"
  title: string | null
  created_at: string
  updated_at: string
}

interface ChatMessageDto {
  id: string
  session_id: string
  role: "user" | "assistant" | "tool"
  content: string
  thinking: string | null
  token_count: number
  created_at: string
}

export type { ChatSessionDto, ChatMessageDto }

export const chatApi = {
  createSession: (personaId: string) =>
    api.post<ChatSessionDto>("/api/chat/sessions", { persona_id: personaId }),

  listSessions: () =>
    api.get<ChatSessionDto[]>("/api/chat/sessions"),

  getSession: (sessionId: string) =>
    api.get<ChatSessionDto>(`/api/chat/sessions/${sessionId}`),

  getMessages: (sessionId: string) =>
    api.get<ChatMessageDto[]>(`/api/chat/sessions/${sessionId}/messages`),

  deleteSession: (sessionId: string) =>
    api.delete<{ status: string }>(`/api/chat/sessions/${sessionId}`),

  updateSession: (sessionId: string, body: { title: string }) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}`, body),

  generateTitle: (sessionId: string) =>
    api.post<{ status: string }>(`/api/chat/sessions/${sessionId}/generate-title`),
}
