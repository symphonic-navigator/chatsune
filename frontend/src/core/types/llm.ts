export type AdapterConfigFieldType = 'string' | 'url' | 'secret' | 'integer'

export interface AdapterConfigFieldHint {
  name: string
  type: AdapterConfigFieldType
  label: string
  required: boolean
  min: number | null
  max: number | null
  placeholder: string | null
}

export interface AdapterTemplate {
  id: string
  display_name: string
  slug_prefix: string
  config_defaults: Record<string, unknown>
  required_config_fields: string[]
}

export interface Adapter {
  adapter_type: string
  display_name: string
  view_id: string
  templates: AdapterTemplate[]
  config_schema: AdapterConfigFieldHint[]
  secret_fields: string[]
}

/**
 * Secret fields are redacted in the server payload:
 * `config[secret_field] = { is_set: boolean }`. Plain fields pass through.
 */
export type SecretFieldView = { is_set: boolean }

export interface Connection {
  id: string
  user_id: string
  adapter_type: string
  display_name: string
  slug: string
  config: Record<string, unknown>
  last_test_status: 'untested' | 'valid' | 'failed' | null
  last_test_error: string | null
  last_test_at: string | null   // ISO string on the wire
  created_at: string
  updated_at: string
  /**
   * System-managed connections are created and maintained by other backend
   * subsystems (e.g. the host's own homelab self-connection). They cannot
   * be edited or deleted via the generic Connection API — mutate the owning
   * resource instead (e.g. the Homelab).
   * Optional for backwards compat on older payloads — treat missing as false.
   */
  is_system_managed?: boolean
}

export interface CreateConnectionRequest {
  adapter_type: string
  display_name: string
  slug: string
  config: Record<string, unknown>
}

export interface UpdateConnectionRequest {
  display_name?: string
  slug?: string
  config?: Record<string, unknown>
}

export interface ModelMetaDto {
  connection_id: string
  connection_slug: string
  connection_display_name: string
  model_id: string
  display_name: string
  context_window: number
  supports_reasoning: boolean
  supports_vision: boolean
  supports_tool_calls: boolean
  parameter_count: string | null
  raw_parameter_count: number | null
  quantisation_level: string | null
  /**
   * Upstream has marked this model as deprecated (scheduled for removal).
   * Optional for backwards compat on older cached payloads — treat missing
   * as false. See shared/dtos/llm.py::ModelMetaDto.is_deprecated.
   */
  is_deprecated?: boolean
  /**
   * How this model bills the user. ``free`` = no cost, ``subscription`` =
   * covered by an upstream plan (Ollama Cloud, nano-gpt subscription tier),
   * ``pay_per_token`` = metered. Optional for backwards compat with older
   * cached payloads — treat missing/null as "unknown".
   */
  billing_category?: 'free' | 'subscription' | 'pay_per_token' | null
  /**
   * Free-form per-model note rendered as a dimmed third line under the
   * row in the model browser. Adapter-set on the backend (`shared/dtos/
   * llm.py::ModelMetaDto.remarks`); the frontend treats it as read-only.
   * Optional/null for every model that has nothing to disclose.
   */
  remarks?: string | null
  unique_id: string
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
  /** null = honour upstream. true/false = force the flag. */
  custom_supports_reasoning: boolean | null
  notes: string | null
  system_prompt_addition: string | null
}

export interface SetUserModelConfigRequest {
  is_favourite?: boolean
  is_hidden?: boolean
  custom_display_name?: string | null
  custom_context_window?: number | null
  custom_supports_reasoning?: boolean | null
  notes?: string | null
  system_prompt_addition?: string | null
}

export interface TestResultResponse {
  valid: boolean
  error: string | null
}
