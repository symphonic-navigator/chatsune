import type { ComponentType } from 'react'
import type { CommandSpec } from '../voice-commands'

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
  /**
   * `true` means the integration participates in the per-persona
   * allowlist: tools / prompt-extensions are only active for a chat when
   * the persona has explicitly opted in. Non-assignable integrations
   * (e.g. voice providers) stay active whenever user-enabled. Backend
   * defaults this to `false`, so an undefined/missing value is treated
   * as `false`.
   */
  assignable?: boolean
}

/** Mirrors UserIntegrationConfigDto from the backend. */
export interface UserIntegrationConfig {
  integration_id: string
  enabled: boolean
  config: Record<string, unknown>
  /**
   * Authoritative "is this integration usable" flag derived server-side
   * from `effective_enabled_map`. For linked-premium integrations
   * (`xai_voice`, `mistral_voice`) it reflects whether the user has a
   * matching Premium Provider Account — the raw `enabled` field is
   * meaningless for those. UI code that decides whether to show a voice
   * provider in a dropdown, or whether an engine is ready, must read
   * this — not `enabled`.
   */
  effective_enabled: boolean
}

/** Result of a response tag execution.
 *
 * Returned synchronously by plugins. Async work (e.g. hardware API calls)
 * goes into the optional sideEffect thunk, which the ResponseTagBuffer
 * fires-and-forgets — the pill and the optional sentence-synced trigger
 * event are decided from the synchronous fields alone. */
export interface TagExecutionResult {
  /** Text shown in the inline pill. Plain text — rendered as a
   *  `<span class="integration-pill">` by `rehypeIntegrationPills`. */
  pillContent: string
  /** When true, the trigger event fires in lockstep with TTS sentence-start.
   *  When false, fires immediately on detection. Ignored in text-only streams
   *  (always fires immediately when no TTS pipeline is active). */
  syncWithTts: boolean
  /** Free, plugin-specific data carried in the trigger event payload. */
  effectPayload: unknown
  /** Optional async work invoked fire-and-forget by ResponseTagBuffer.
   *  Errors are logged; do not affect pill or event emission. */
  sideEffect?: () => Promise<void>
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

  /** Execute a response tag found in the LLM output. Synchronous — must
   *  return pill content and sync-decision without awaiting. Async work
   *  goes into the optional sideEffect field of the result. */
  executeTag?: (command: string, args: string[], config: Record<string, unknown>) => TagExecutionResult

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

  /**
   * Voice commands this integration provides. Registered when the plugin
   * activates (with source `integration:${id}`) and unregistered when it
   * deactivates. The lifecycle code overwrites the `source` field so
   * plugins cannot misrepresent their origin.
   */
  voiceCommands?: CommandSpec[]
}

/** Frontend-bus event payload for INTEGRATION_INLINE_TRIGGER.
 *  Mirrors the shared backend DTO (kept structurally identical so a
 *  future backend audit-emit path is a non-breaking addition). */
export interface IntegrationInlineTrigger {
  integration_id: string
  command: string
  args: string[]
  payload: unknown
  source: 'live_stream' | 'text_only' | 'read_aloud'
  correlation_id: string
  timestamp: string
}
