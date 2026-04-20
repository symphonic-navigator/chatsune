import type { ComponentType } from 'react'

/** Option for select/dropdown fields with dynamic sources. */
export interface Option {
  value: string | null
  label: string
}

/** Mirrors IntegrationConfigFieldDto from the backend. */
export interface IntegrationConfigField {
  key: string
  label: string
  field_type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'textarea'
  placeholder: string
  required: boolean
  description: string
  secret?: boolean
  options_source?: 'plugin'
  options?: Array<{ value: string; label: string }>
}

/** Mirrors IntegrationDefinitionDto from the backend. */
export interface IntegrationDefinition {
  id: string
  display_name: string
  description: string
  icon: string
  execution_mode: 'frontend' | 'backend' | 'hybrid'
  config_fields: IntegrationConfigField[]
  has_tools: boolean
  has_response_tags: boolean
  has_prompt_extension: boolean
  capabilities: string[]
  persona_config_fields: IntegrationConfigField[]
  /**
   * `false` means the integration is backend-proxied: secrets stay on the
   * server and the plugin must activate without waiting for browser-side
   * secret hydration. Defaults to `true` to preserve Mistral-style
   * browser-direct behaviour for integrations that don't set it.
   */
  hydrate_secrets?: boolean
  /**
   * When set, the api_key for this integration is sourced from the user's
   * Premium Provider Account with the given provider id (e.g. `xai` for
   * `xai_voice`). When set, the IntegrationsTab hides the api_key input
   * and the enable/disable toggle, pointing the user at the Providers tab.
   */
  linked_premium_provider?: string | null
}

/** Mirrors UserIntegrationConfigDto from the backend. */
export interface UserIntegrationConfig {
  integration_id: string
  enabled: boolean
  config: Record<string, unknown>
}

/** Result of a response tag execution. */
export interface TagExecutionResult {
  success: boolean
  displayText: string
}

/** Health status reported by a plugin's healthCheck. */
export type HealthStatus = 'connected' | 'reachable' | 'unreachable' | 'unknown'

/**
 * Frontend plugin interface. Each integration registers one of these.
 * Only frontend/hybrid integrations need most of these — backend-only
 * integrations use just metadata + config UI.
 */
export interface IntegrationPlugin {
  id: string

  /** Execute a response tag found in the LLM output. */
  executeTag?: (command: string, args: string[], config: Record<string, unknown>) => Promise<TagExecutionResult>

  /** Execute a tool call dispatched from the backend. */
  executeTool?: (toolName: string, args: Record<string, unknown>, config: Record<string, unknown>) => Promise<string>

  /** Check whether the integration is reachable. */
  healthCheck?: (config: Record<string, unknown>) => Promise<HealthStatus>

  /** Emergency stop — halt all activity immediately. */
  emergencyStop?: (config: Record<string, unknown>) => Promise<void>

  /** Custom config UI component (rendered in IntegrationsTab). */
  ConfigComponent?: ComponentType<{ config: Record<string, unknown>; onChange: (config: Record<string, unknown>) => void }>

  /** Renders below the generic config form; not used if ConfigComponent is set. */
  ExtraConfigComponent?: ComponentType

  /** Dynamic options for persona_config_fields with options_source = 'plugin'. */
  getPersonaConfigOptions?(fieldKey: string): Option[] | Promise<Option[]>

  /** Called when the integration becomes active (enabled + secrets hydrated if any). */
  onActivate?(): void

  /** Called when the integration is disabled or its secrets are cleared. */
  onDeactivate?(): void
}
