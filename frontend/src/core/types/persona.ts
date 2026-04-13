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
  model_unique_id: string;
  system_prompt: string;
  temperature: number;
  reasoning_enabled: boolean;
  soft_cot_enabled: boolean;
  vision_fallback_model: string | null;
  nsfw: boolean;
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
  voice_config: {
    dialogue_voice: string | null
    narrator_voice: string | null
    auto_read: boolean
    roleplay_mode: boolean
  } | null;
  created_at: string;
  updated_at: string;
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
  colour_scheme?: ChakraColour;
  display_order?: number;
  pinned?: boolean;
  profile_image?: string | null;
  voice_config?: PersonaDto['voice_config'];
}
