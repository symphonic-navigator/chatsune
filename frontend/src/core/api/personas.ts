import { api } from "./client"
import type {
  PersonaDto,
  CreatePersonaRequest,
  UpdatePersonaRequest,
} from "../types/persona"

export const personasApi = {
  list: () =>
    api.get<PersonaDto[]>("/api/personas"),

  get: (personaId: string) =>
    api.get<PersonaDto>(`/api/personas/${personaId}`),

  create: (data: CreatePersonaRequest) =>
    api.post<PersonaDto>("/api/personas", data),

  replace: (personaId: string, data: CreatePersonaRequest) =>
    api.put<PersonaDto>(`/api/personas/${personaId}`, data),

  update: (personaId: string, data: UpdatePersonaRequest) =>
    api.patch<PersonaDto>(`/api/personas/${personaId}`, data),

  remove: (personaId: string) =>
    api.delete<{ status: string }>(`/api/personas/${personaId}`),

  reorder: async (orderedIds: string[]): Promise<void> => {
    await api.patch("/api/personas/reorder", { ordered_ids: orderedIds });
  },

  getSystemPromptPreview: (personaId: string) =>
    api.get<{ preview: string }>(`/api/personas/${personaId}/system-prompt-preview`),
}
