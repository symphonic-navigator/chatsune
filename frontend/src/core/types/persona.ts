import type { ChakraColour } from "./chakra";

export interface ProfileCrop {
  x: number;
  y: number;
  zoom: number;
  width: number;
  height: number;
}

export interface PersonaDto {
  id: string;
  user_id: string;
  name: string;
  tagline: string;
  // null after the connections-refactor migration nulled stale IDs, or
  // after the persona's connection was deleted (see INS-019).
  model_unique_id: string | null;
  system_prompt: string;
  temperature: number;
  reasoning_enabled: boolean;
  soft_cot_enabled: boolean;
  vision_fallback_model: string | null;
  nsfw: boolean;
  use_memory: boolean;
  colour_scheme: ChakraColour;
  display_order: number;
  monogram: string;
  pinned: boolean;
  profile_image: string | null;
  profile_crop: ProfileCrop | null;
  mcp_config: {
    excluded_gateways: string[]
    excluded_servers: string[]
    excluded_tools: string[]
  } | null;
  integrations_config: {
    enabled_integration_ids: string[]
  } | null;
  voice_config?: {
    dialogue_voice: string | null
    narrator_voice: string | null
    auto_read: boolean
    narrator_mode: 'off' | 'play' | 'narrate'
    dialogue_speed: number
    dialogue_pitch: number
    narrator_speed: number
    narrator_pitch: number
    // tts_provider_id — ID of the TTS integration that speaks for this
    // persona. null means "fall back to the first enabled TTS provider"
    // (the resolver applies the fallback). Mirrors VoiceConfigDto in
    // shared/dtos/persona.py.
    tts_provider_id?: string | null
  } | null;
  integration_configs?: Record<string, Record<string, unknown>>;
  created_at: string;
  updated_at: string;
  // Most recent chat-session creation or resume. Optional for backwards
  // compatibility — sidebar LRU sort falls back to created_at when missing.
  last_used_at?: string | null;
}

export interface CreatePersonaRequest {
  name: string;
  tagline: string;
  model_unique_id: string;
  system_prompt: string;
  temperature?: number;
  reasoning_enabled?: boolean;
  soft_cot_enabled?: boolean;
  vision_fallback_model?: string | null;
  nsfw?: boolean;
  use_memory?: boolean;
  colour_scheme?: ChakraColour;
  display_order?: number;
  pinned?: boolean;
  profile_image?: string | null;
}

export interface UpdatePersonaRequest {
  name?: string;
  tagline?: string;
  model_unique_id?: string;
  system_prompt?: string;
  temperature?: number;
  reasoning_enabled?: boolean;
  soft_cot_enabled?: boolean;
  vision_fallback_model?: string | null;
  nsfw?: boolean;
  use_memory?: boolean;
  colour_scheme?: ChakraColour;
  display_order?: number;
  pinned?: boolean;
  profile_image?: string | null;
  integration_configs?: Record<string, Record<string, unknown>>;
  voice_config?: PersonaDto['voice_config'];
}
