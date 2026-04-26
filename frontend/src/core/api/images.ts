/**
 * TypeScript types mirroring shared/dtos/images.py.
 *
 * Keep in sync with the Python DTOs — no codegen pipeline exists;
 * changes on the Python side must be reflected here by hand.
 */

// --- per-group typed configs (discriminated union via group_id) ---------------

export interface XaiImagineConfig {
  group_id: 'xai_imagine'
  tier: 'normal' | 'pro'
  resolution: '1k' | '2k'
  aspect: '1:1' | '16:9' | '9:16' | '4:3' | '3:4'
  n: number
}

/**
 * Discriminated union of all image-group configs.
 * Narrow with: switch (cfg.group_id) { case 'xai_imagine': ... }
 * Extend this union when new image groups are added (Seedream, FLUX, etc.).
 */
export type ImageGroupConfig = XaiImagineConfig


// --- generation result items (per-image; discriminated by kind) ---------------

export interface GeneratedImageResult {
  kind: 'image'
  id: string
  width: number
  height: number
  model_id: string
  description?: string | null
}

export interface ModeratedRejection {
  kind: 'moderated'
  reason?: string | null
}

/**
 * One slot in a TTI tool-call response: either a successfully generated image
 * or a moderated rejection.  Narrow with: switch (item.kind) { ... }
 */
export type ImageGenItem = GeneratedImageResult | ModeratedRejection


// --- message-level reference (rendered inline under assistant message) ---------

export interface ImageRefDto {
  id: string
  blob_url: string
  thumb_url: string
  width: number
  height: number
  prompt: string
  model_id: string
  tool_call_id: string
  /**
   * JPEG thumbnail bytes inline (base64). Use as
   * `<img src="data:image/jpeg;base64,${thumbnail_b64}">`. The auth model
   * is Bearer JWT, which browsers cannot attach to <img> subresource
   * requests, so the URL endpoints are only useful for authenticated
   * fetches (e.g. lightbox via fetch + URL.createObjectURL).
   */
  thumbnail_b64?: string | null
}


// --- gallery REST DTOs --------------------------------------------------------

export interface GeneratedImageSummaryDto {
  id: string
  thumb_url: string
  width: number
  height: number
  prompt: string
  model_id: string
  /** ISO 8601 timestamp */
  generated_at: string
  /** JPEG thumbnail base64 — see ImageRefDto.thumbnail_b64. */
  thumbnail_b64?: string | null
}

export interface GeneratedImageDetailDto extends GeneratedImageSummaryDto {
  blob_url: string
  config_snapshot: Record<string, unknown>
  connection_id: string
  group_id: string
}


// --- discovery DTO for GET /api/images/config ---------------------------------

export interface ConnectionImageGroupsDto {
  connection_id: string
  connection_display_name: string
  group_ids: string[]
}

export interface ActiveImageConfigDto {
  connection_id: string
  group_id: string
  /** Raw config object — narrow to the appropriate typed config via group_id. */
  config: Record<string, unknown>
}
