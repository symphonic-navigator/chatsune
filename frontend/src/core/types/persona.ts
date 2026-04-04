export interface PersonaDto {
  id: string
  user_id: string
  name: string
  tagline: string
  model_unique_id: string
  system_prompt: string
  temperature: number
  reasoning_enabled: boolean
  nsfw: boolean
  colour_scheme: string
  display_order: number
  created_at: string
  updated_at: string
}

export interface CreatePersonaRequest {
  name: string
  tagline: string
  model_unique_id: string
  system_prompt: string
  temperature?: number
  reasoning_enabled?: boolean
  nsfw?: boolean
  colour_scheme?: string
  display_order?: number
}

export interface UpdatePersonaRequest {
  name?: string
  tagline?: string
  model_unique_id?: string
  system_prompt?: string
  temperature?: number
  reasoning_enabled?: boolean
  nsfw?: boolean
  colour_scheme?: string
  display_order?: number
}
