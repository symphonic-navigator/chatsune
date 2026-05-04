// Images tab — wraps the existing `GalleryGrid` so it can accept a
// ``projectFilter`` prop and share the same shape as the other
// "user-modal" tabs (HistoryTab, UploadsTab, ArtefactsTab).
//
// Two modes:
//   - Unfiltered (UserModal's My data → Images): defer to the
//     existing `GalleryGrid` so the global gallery store keeps its
//     pagination + lightbox semantics.
//   - Filtered (Project-Detail-Overlay → Images): render a small
//     project-scoped grid that calls `imagesApi.listImages({
//     project_id })` directly. The grid is intentionally minimal —
//     no lightbox, no infinite scroll — because Phase 9 only needs
//     a "what does this project contain" surface; the rich gallery
//     behaviour belongs in the global tab.

import { useEffect, useState } from 'react'
import { GalleryGrid } from '../../../features/images/gallery/GalleryGrid'
import { imagesApi } from '../../../features/images/api'
import type { GeneratedImageSummaryDto } from '@/core/api/images'

interface ImagesTabProps {
  /**
   * Mindspace: when set, the tab scopes to a single project's
   * generated images. Phase 9 / spec §6.5 Tab 6.
   */
  projectFilter?: string
}

export function ImagesTab({ projectFilter }: ImagesTabProps = {}) {
  if (!projectFilter) {
    return (
      <div className="flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        <GalleryGrid />
      </div>
    )
  }
  return <ProjectScopedGallery projectId={projectFilter} />
}

interface ProjectScopedGalleryProps {
  projectId: string
}

function ProjectScopedGallery({ projectId }: ProjectScopedGalleryProps) {
  const [items, setItems] = useState<GeneratedImageSummaryDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    imagesApi
      .listImages({ project_id: projectId, limit: 200 })
      .then((res) => {
        if (cancelled) return
        setItems(res)
      })
      .catch(() => {
        if (cancelled) return
        setError('Could not load images.')
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  return (
    <div className="flex-1 overflow-y-auto p-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
      <h2 className="text-[15px] font-semibold text-white/85 mb-4">
        Generated images
      </h2>

      {loading && items.length === 0 && (
        <p className="text-white/40 text-sm">Loading…</p>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="text-white/60 text-sm">
          No generated images in this project yet.
        </p>
      )}
      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {items.map((it) => (
          <div
            key={it.id}
            data-testid={`project-image-${it.id}`}
            className="block rounded-md overflow-hidden relative"
            aria-label={`Image: ${it.prompt.slice(0, 80)}`}
          >
            <img
              src={
                it.thumbnail_b64
                  ? `data:image/jpeg;base64,${it.thumbnail_b64}`
                  : it.thumb_url
              }
              alt={it.prompt}
              className="rounded-md w-full aspect-square object-cover"
              loading="lazy"
            />
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0 hover:opacity-100 transition-opacity pointer-events-none">
              <span className="text-xs text-white truncate block">
                {it.prompt}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
