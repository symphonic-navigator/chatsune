import { create } from 'zustand'
import { imagesApi } from './api'
import type {
  ActiveImageConfigDto,
  ConnectionImageGroupsDto,
  GeneratedImageSummaryDto,
  ImageGroupConfig,
} from '@/core/api/images'

/** How many images to fetch per page. */
const PAGE_SIZE = 24

type ImagesStore = {
  available: ConnectionImageGroupsDto[]
  active: ActiveImageConfigDto | null
  gallery: GeneratedImageSummaryDto[]
  galleryLoading: boolean
  galleryHasMore: boolean

  loadConfig: () => Promise<void>
  applyConfig: (payload: {
    connection_id: string
    group_id: string
    config: ImageGroupConfig
  }) => Promise<void>

  /** Resets the gallery cache and loads the first page. */
  loadGalleryFirst: () => Promise<void>
  /** Appends the next page to the existing gallery cache. */
  loadGalleryMore: () => Promise<void>
  /** Deletes an image from the backend and removes it from the cache. */
  removeFromGallery: (id: string) => Promise<void>
}

export const useImagesStore = create<ImagesStore>((set, get) => ({
  available: [],
  active: null,
  gallery: [],
  galleryLoading: false,
  galleryHasMore: true,

  loadConfig: async () => {
    try {
      const discovery = await imagesApi.getImageConfig()
      set({ available: discovery.available, active: discovery.active })
    } catch (err) {
      console.error('[images] Failed to load config:', err)
    }
  },

  applyConfig: async (payload) => {
    const result = await imagesApi.setImageConfig(payload)
    set({ active: result })
  },

  loadGalleryFirst: async () => {
    if (get().galleryLoading) return
    set({ galleryLoading: true, gallery: [], galleryHasMore: true })
    try {
      const items = await imagesApi.listImages({ limit: PAGE_SIZE })
      set({
        gallery: items,
        galleryHasMore: items.length === PAGE_SIZE,
      })
    } catch (err) {
      console.error('[images] Failed to load gallery:', err)
    } finally {
      set({ galleryLoading: false })
    }
  },

  loadGalleryMore: async () => {
    const { gallery, galleryLoading, galleryHasMore } = get()
    if (galleryLoading || !galleryHasMore) return
    set({ galleryLoading: true })
    try {
      // Use the oldest item's timestamp as the cursor so we page backwards in time.
      const before = gallery.length > 0 ? gallery[gallery.length - 1].generated_at : undefined
      const items = await imagesApi.listImages({ limit: PAGE_SIZE, before })
      set((s) => ({
        gallery: [...s.gallery, ...items],
        galleryHasMore: items.length === PAGE_SIZE,
      }))
    } catch (err) {
      console.error('[images] Failed to load more gallery images:', err)
    } finally {
      set({ galleryLoading: false })
    }
  },

  removeFromGallery: async (id) => {
    await imagesApi.deleteImage(id)
    set((s) => ({ gallery: s.gallery.filter((img) => img.id !== id) }))
  },
}))
