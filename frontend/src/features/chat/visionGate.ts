import type { EnrichedModelDto } from '../../core/types/llm'
import type { PersonaDto } from '../../core/types/persona'

/**
 * Resolver that maps a model unique id to its enriched model record (or
 * ``null`` when the id no longer resolves — e.g. the connection has been
 * removed). Mirrors the shape returned by ``useEnrichedModels``.
 */
export type ModelLookup = (uid: string) => EnrichedModelDto | null

/**
 * User-facing message shown whenever an image upload is blocked because
 * the persona's effective vision capability is missing. The wording must
 * spell out the two ways to unblock — pick a vision-capable model OR
 * configure a vision-fallback model in persona settings.
 */
export const VISION_BLOCKED_MESSAGE =
  "This model can't see images. Pick a vision-capable model, or set a vision-fallback model in persona settings to enable image uploads."

/**
 * Returns ``true`` when the persona can ingest images for inference:
 *   - the primary model has ``supports_vision``, OR
 *   - the persona has a ``vision_fallback_model`` configured AND that
 *     fallback itself has ``supports_vision``.
 *
 * A persona with no model selected, or with a fallback that has been
 * removed / does not support vision, is treated as image-blocked.
 *
 * Pure function — no React hooks, suitable for use inside event handlers,
 * other helpers, and tests. The model-resolver is provided by callers so
 * the predicate stays decoupled from any specific data hook.
 */
export function canSendImages(
  persona: Pick<PersonaDto, 'model_unique_id' | 'vision_fallback_model'> | null,
  findByUniqueId: ModelLookup,
): boolean {
  if (!persona) return false
  if (persona.model_unique_id) {
    const primary = findByUniqueId(persona.model_unique_id)
    if (primary?.supports_vision) return true
  }
  if (persona.vision_fallback_model) {
    const fallback = findByUniqueId(persona.vision_fallback_model)
    if (fallback?.supports_vision) return true
  }
  return false
}

/**
 * ``true`` for File objects whose MIME type begins with ``image/``. Used
 * by the upload-side gate to split user-picked / dropped / pasted files
 * into image vs non-image so non-image attachments still flow through
 * when the persona is image-blocked.
 */
export function isImageFile(file: File): boolean {
  return file.type.startsWith('image/')
}

/**
 * ``true`` for storage records whose ``media_type`` begins with
 * ``image/``. Used by the upload-browser pick handler so the user cannot
 * attach an existing image when the persona is image-blocked.
 */
export function isImageMediaType(mediaType: string | null | undefined): boolean {
  return !!mediaType && mediaType.startsWith('image/')
}
