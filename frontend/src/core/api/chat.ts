import { api } from "./client"
import type { AttachmentRefDto } from "./storage"
import type { ImageRefDto } from "./images"

export interface KnowledgeContextItem {
  library_name: string
  document_title: string
  heading_path?: string[]
  preroll_text?: string | null
  content: string
  score?: number | null
  source: 'search' | 'trigger'
  triggered_by?: string | null
}

export interface PtiOverflow {
  dropped_count: number
  dropped_titles: string[]
}

interface ChatSessionDto {
  id: string
  user_id: string
  persona_id: string
  state: "idle" | "streaming" | "requires_action"
  title: string | null
  tools_enabled: boolean
  auto_read: boolean
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

interface ArtefactRef {
  artefact_id: string
  handle: string
  title: string
  artefact_type: string
  operation: 'create' | 'update'
}

interface ToolCallRef {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  success: boolean
  /** Number of image slots rejected by the content-moderation filter. */
  moderated_count?: number
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
  knowledge_context: KnowledgeContextItem[] | null
  pti_overflow?: PtiOverflow | null
  vision_descriptions_used?: VisionDescriptionSnapshot[] | null
  created_at: string
  status?: 'completed' | 'aborted' | 'refused'
  refusal_text?: string | null
  artefact_refs?: ArtefactRef[] | null
  tool_calls?: ToolCallRef[] | null
  image_refs?: ImageRefDto[] | null
  usage?: { input_tokens?: number; output_tokens?: number } | null
  time_to_first_token_ms?: number | null
  tokens_per_second?: number | null
  generation_duration_ms?: number | null
  provider_name?: string | null
  model_name?: string | null
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
  ArtefactRef,
  ToolCallRef,
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
    api.get<{
      messages: ChatMessageDto[]
      context_status: 'green' | 'yellow' | 'orange' | 'red'
      context_fill_percentage: number
      context_used_tokens?: number
      context_max_tokens?: number
    }>(`/api/chat/sessions/${sessionId}/messages`),

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

  updateSessionToggles: (
    sessionId: string,
    patch: { tools_enabled?: boolean; auto_read?: boolean },
  ) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}/toggles`, patch),

  updateSessionPinned: (sessionId: string, pinned: boolean) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}/pinned`, { pinned }),

  listToolGroups: () =>
    api.get<ToolGroupDto[]>("/api/chat/tools"),
}
