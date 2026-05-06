// Mindspace project DTOs — mirror of backend Pydantic models in
// `shared/dtos/project.py` and the SessionProjectUpdateDto in
// `shared/dtos/chat.py`. Field names match the wire format exactly so
// the JSON returned from the API can be assigned directly without any
// re-shaping. Keep this file in lockstep with the Pydantic side.

/**
 * A project (Mindspace) — the top-level container that a user can
 * group chat sessions, attached uploads, artefacts, and images into.
 * Returned by `GET /api/projects` and `GET /api/projects/{id}`.
 */
export interface ProjectDto {
  id: string
  user_id: string
  title: string
  emoji: string | null
  /**
   * Free-form description. Optional/nullable: pre-Mindspace documents
   * either carry an empty string or no value at all; both round-trip.
   */
  description: string | null
  nsfw: boolean
  pinned: boolean
  sort_order: number
  /**
   * Knowledge libraries attached to this project. Defaults to `[]` for
   * legacy documents that lack the field entirely.
   */
  knowledge_library_ids: string[]
  /**
   * Optional per-project Custom Instructions injected into the
   * assembled system prompt between model-instructions and persona.
   * `null` for projects without CI.
   */
  system_prompt: string | null
  created_at: string
  updated_at: string
}

/**
 * Body for `POST /api/projects`. ``title`` is required; everything else
 * has a server-side default.
 */
export interface ProjectCreateDto {
  title: string
  emoji?: string | null
  description?: string | null
  nsfw?: boolean
  knowledge_library_ids?: string[]
  system_prompt?: string | null
}

/**
 * Body for `PATCH /api/projects/{id}`. Every field is optional; omit a
 * field to leave it unchanged. Sending `null` for nullable fields
 * (``emoji``, ``description``) clears them server-side.
 */
export interface ProjectUpdateDto {
  title?: string
  emoji?: string | null
  description?: string | null
  nsfw?: boolean
  knowledge_library_ids?: string[]
  /**
   * Omit to leave unchanged. `null` clears the CI server-side;
   * a string sets it.
   */
  system_prompt?: string | null
}

/**
 * Per-project usage counts surfaced by
 * `GET /api/projects/{id}?include_usage=true`. Used by the delete-modal
 * to show what a full purge would remove.
 */
export interface ProjectUsageDto {
  chat_count: number
  upload_count: number
  artefact_count: number
  image_count: number
}

/**
 * Body for `PATCH /api/projects/{id}/pinned` — toggles the sidebar pin.
 */
export interface ProjectPinnedDto {
  pinned: boolean
}

/**
 * Body for `PATCH /api/chat/sessions/{id}/project` — assigns
 * (`projectId`) or detaches (`null`) a chat session from a project.
 */
export interface SessionProjectUpdateDto {
  project_id: string | null
}

/**
 * Shape returned by `GET /api/projects/{id}` when ``include_usage=true``.
 * The ``usage`` field is absent on the basic GET.
 */
export type ProjectWithUsage = ProjectDto & { usage?: ProjectUsageDto }
