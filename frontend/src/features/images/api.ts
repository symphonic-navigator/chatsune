import { api, apiUrl, currentAccessToken } from '@/core/api/client'
import type {
  ActiveImageConfigDto,
  ConnectionImageGroupsDto,
  GeneratedImageDetailDto,
  GeneratedImageSummaryDto,
  ImageGenItem,
  ImageGroupConfig,
} from '@/core/api/images'

export type ImageConfigDiscovery = {
  available: ConnectionImageGroupsDto[]
  active: ActiveImageConfigDto | null
}

export const imagesApi = {
  /** List gallery images, newest-first. Pass `before` (ISO 8601) for cursor-based pagination. */
  listImages: (opts?: { limit?: number; before?: string }): Promise<GeneratedImageSummaryDto[]> => {
    const params = new URLSearchParams()
    if (opts?.limit !== undefined) params.set('limit', String(opts.limit))
    if (opts?.before !== undefined) params.set('before', opts.before)
    const qs = params.toString()
    return api.get<GeneratedImageSummaryDto[]>(`/api/images${qs ? `?${qs}` : ''}`)
  },

  getImage: (id: string): Promise<GeneratedImageDetailDto> =>
    api.get<GeneratedImageDetailDto>(`/api/images/${id}`),

  deleteImage: (id: string): Promise<void> =>
    api.delete<void>(`/api/images/${id}`),

  /** Fetches both the available connections (with group ids) and the user's active config. */
  getImageConfig: (): Promise<ImageConfigDiscovery> =>
    api.get<ImageConfigDiscovery>('/api/images/config'),

  setImageConfig: (payload: {
    connection_id: string
    group_id: string
    config: ImageGroupConfig
  }): Promise<ActiveImageConfigDto> =>
    api.post<ActiveImageConfigDto>('/api/images/config', payload),

  /**
   * Adapter-agnostic one-off image generation for the cockpit "Test image"
   * button. The backend resolves the connection (regular or premium),
   * generates without persisting, and returns base64 thumbnail data URIs
   * inline so the cockpit can preview them without a follow-up GET.
   */
  testImagine: (payload: {
    connection_id: string
    group_id: string
    config: ImageGroupConfig
    prompt?: string
  }): Promise<{
    successful_count: number
    moderated_count: number
    thumbs_data_uris: string[]
  }> =>
    api.post('/api/images/test', payload),
}

/**
 * Fetch the full-size blob for an image via an authenticated GET.
 *
 * Browsers cannot attach an Authorization header to <img src="..."> subresource
 * requests, so direct URL rendering always 401s. This helper does the fetch
 * manually with the Bearer token so the caller can create an ObjectURL instead.
 */
export async function getImageBlob(id: string): Promise<Blob> {
  const token = currentAccessToken()
  const res = await fetch(apiUrl(`/api/images/${id}/blob`), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to load image: ${res.status}`)
  return res.blob()
}

// Deprecated re-export (kept to surface a clear error if any caller
// still relies on the old per-adapter URL signature).
export type _DeprecatedImageGenItem = ImageGenItem
