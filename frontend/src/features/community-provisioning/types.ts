/**
 * Frontend mirrors of the Community Provisioning DTOs defined in
 * `shared/dtos/llm.py`. Only the fields the UI actually consumes are
 * typed here; add more as the host UI grows.
 */

export type HomelabStatus = 'active' | 'revoked'

export interface HomelabEngineInfo {
  type: string
  version: string | null
}

export interface Homelab {
  homelab_id: string
  display_name: string
  host_key_hint: string
  status: HomelabStatus
  created_at: string
  last_seen_at: string | null
  last_sidecar_version: string | null
  last_engine_info: HomelabEngineInfo | null
  is_online: boolean
  /**
   * Total simultaneous requests across ALL users of this homelab. Defaults
   * to 3 on the wire; optional here only to keep older payloads decoding.
   */
  max_concurrent_requests: number
  /**
   * Slug for the host's own self-access connection, auto-created alongside
   * the homelab. Nullable only for older homelabs created before this field
   * existed; new creates always carry a value.
   */
  host_slug: string | null
}

export interface HomelabCreated extends Homelab {
  plaintext_host_key: string
}

export interface HomelabHostKeyRegenerated extends Homelab {
  plaintext_host_key: string
}

export type ApiKeyStatus = 'active' | 'revoked'

export interface ApiKey {
  api_key_id: string
  homelab_id: string
  display_name: string
  api_key_hint: string
  allowed_model_slugs: string[]
  status: ApiKeyStatus
  created_at: string
  revoked_at: string | null
  last_used_at: string | null
  /** Per-API-Key concurrency ceiling. Default 1 on the wire. */
  max_concurrent: number
}

export interface ApiKeyCreated extends ApiKey {
  plaintext_api_key: string
}

export interface CreateHomelabInput {
  display_name: string
  host_slug: string
  max_concurrent_requests?: number
}

export interface UpdateHomelabInput {
  display_name?: string
  max_concurrent_requests?: number
}

export interface CreateApiKeyInput {
  display_name: string
  allowed_model_slugs: string[]
  max_concurrent?: number
}

export interface UpdateApiKeyInput {
  display_name?: string
  allowed_model_slugs?: string[]
  max_concurrent?: number
}
