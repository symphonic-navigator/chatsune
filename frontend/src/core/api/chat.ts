import { api } from "./client"
import type { AttachmentRefDto } from "./storage"
import type { RetrievedChunkDto } from "../types/knowledge"

interface ChatSessionDto {
  id: string
  user_id: string
  persona_id: string
  model_unique_id: string
  state: "idle" | "streaming" | "requires_action"
  title: string | null
  disabled_tool_groups: string[]
  reasoning_override: boolean | null
  pinned: boolean
  created_at: string
  updated_at: string
}

interface WebSearchContextItem {
  title: string
  url: string
  snippet: string
  source_type?: "search" | "fetch"
}

interface VisionDescriptionSnapshot {
  file_id: string
  display_name: string
  model_id: string
  text: string
}

interface ChatMessageDto {
  id: string
  session_id: string
  role: "user" | "assistant" | "tool"
  content: string
  thinking: string | null
  token_count: number
  attachments: AttachmentRefDto[] | null
  web_search_context: WebSearchContextItem[] | null
  knowledge_context: RetrievedChunkDto[] | null
  vision_descriptions_used?: VisionDescriptionSnapshot[] | null
  created_at: string
}

interface ToolGroupDto {
  id: string
  display_name: string
  description: string
  side: "server" | "client"
  toggleable: boolean
}

export type {
  ChatSessionDto,
  ChatMessageDto,
  WebSearchContextItem,
  VisionDescriptionSnapshot,
  ToolGroupDto,
  AttachmentRefDto,
}

export const chatApi = {
  createSession: (personaId: string) =>
    api.post<ChatSessionDto>("/api/chat/sessions", { persona_id: personaId }),

  listSessions: () =>
    api.get<ChatSessionDto[]>("/api/chat/sessions"),

  searchSessions: (params: {
    q: string
    persona_id?: string
    exclude_persona_ids?: string[]
  }) => {
    const searchParams = new URLSearchParams({ q: params.q })
    if (params.persona_id) searchParams.set('persona_id', params.persona_id)
    if (params.exclude_persona_ids?.length) {
      searchParams.set('exclude_persona_ids', params.exclude_persona_ids.join(','))
    }
    return api.get<ChatSessionDto[]>(`/api/chat/sessions/search?${searchParams}`)
  },

  getSession: (sessionId: string) =>
    api.get<ChatSessionDto>(`/api/chat/sessions/${sessionId}`),

  getMessages: (sessionId: string) =>
    api.get<ChatMessageDto[]>(`/api/chat/sessions/${sessionId}/messages`),

  deleteSession: (sessionId: string) =>
    api.delete<{ status: string }>(`/api/chat/sessions/${sessionId}`),

  restoreSession: (sessionId: string) =>
    api.post<{ status: string }>(`/api/chat/sessions/${sessionId}/restore`),

  updateSession: (sessionId: string, body: { title: string }) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}`, body),

  generateTitle: (sessionId: string) =>
    api.post<{ status: string }>(`/api/chat/sessions/${sessionId}/generate-title`),

  updateSessionReasoning: (sessionId: string, reasoningOverride: boolean | null) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}/reasoning`, {
      reasoning_override: reasoningOverride,
    }),

  updateSessionTools: (sessionId: string, disabledToolGroups: string[]) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}/tools`, {
      disabled_tool_groups: disabledToolGroups,
    }),

  updateSessionPinned: (sessionId: string, pinned: boolean) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}/pinned`, { pinned }),

  listToolGroups: () =>
    api.get<ToolGroupDto[]>("/api/chat/tools"),
}
