export interface ProviderCredentialDto {
  provider_id: string
  display_name: string
  is_configured: boolean
  requires_key_for_listing: boolean
  test_status: "untested" | "valid" | "failed" | null
  last_test_error: string | null
  created_at: string | null
}

export interface SetProviderKeyRequest {
  api_key: string
}

export type ModelRating = "available" | "recommended" | "not_recommended"

export interface ModelCurationDto {
  overall_rating: ModelRating
  hidden: boolean
  admin_description: string | null
  last_curated_at: string | null
  last_curated_by: string | null
}

export interface SetModelCurationRequest {
  overall_rating: ModelRating
  hidden: boolean
  admin_description?: string | null
}

export interface ModelMetaDto {
  provider_id: string
  model_id: string
  display_name: string
  context_window: number
  supports_reasoning: boolean
  supports_vision: boolean
  supports_tool_calls: boolean
  parameter_count: string | null
  quantisation_level: string | null
  curation: ModelCurationDto | null
  unique_id: string
}

export interface FaultyProviderDto {
  provider_id: string
  display_name: string
  error_message: string
}

/** Model enriched with the user's per-model configuration (merged client-side). */
export interface EnrichedModelDto extends ModelMetaDto {
  user_config: UserModelConfigDto | null
}

export interface UserModelConfigDto {
  model_unique_id: string
  is_favourite: boolean
  is_hidden: boolean
  custom_display_name: string | null
  custom_context_window: number | null
  notes: string | null
  system_prompt_addition: string | null
}

export interface SetUserModelConfigRequest {
  is_favourite?: boolean
  is_hidden?: boolean
  custom_display_name?: string | null
  custom_context_window?: number | null
  notes?: string | null
  system_prompt_addition?: string | null
}

export interface TestKeyResponse {
  valid: boolean
  error: string | null
}
