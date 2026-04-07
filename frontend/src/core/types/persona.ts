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
}
