import { useEffect } from 'react'
import { useImagesStore } from '../store'
import type { GeneratedImageSummaryDto } from '@/core/api/images'

interface GeneratedImagesTabProps {
  onPick: (image: GeneratedImageSummaryDto) => void
}

export function GeneratedImagesTab({ onPick }: GeneratedImagesTabProps) {
  const { gallery, galleryLoading, galleryHasMore, loadGalleryFirst, loadGalleryMore } =
    useImagesStore()

  useEffect(() => {
    if (gallery.length === 0) void loadGalleryFirst()
  }, [gallery.length, loadGalleryFirst])

  return (
    <div className="p-3">
      {gallery.length === 0 && !galleryLoading && (
        <div className="py-6 text-center text-sm text-white/60">
          No generated images yet.
        </div>
      )}

      {galleryLoading && gallery.length === 0 && (
        <div className="py-6 text-center text-[12px] text-white/20">Loading...</div>
      )}

      <div className="grid grid-cols-3 gap-2 max-h-[300px] overflow-auto">
        {gallery.map((it) => (
          <button
            key={it.id}
            type="button"
            onClick={() => onPick(it)}
            className="block focus:outline-none rounded-md overflow-hidden hover:ring-2 hover:ring-white/40"
            aria-label={`Attach: ${it.prompt.slice(0, 80)}`}
          >
            <img
              src={it.thumb_url}
              alt={it.prompt}
              className="rounded-md w-full aspect-square object-cover"
              loading="lazy"
            />
          </button>
        ))}
      </div>

      {galleryHasMore && !galleryLoading && gallery.length > 0 && (
        <div className="flex justify-center mt-3">
          <button
            type="button"
            onClick={() => void loadGalleryMore()}
            className="text-xs px-3 py-1 rounded-md bg-white/10 hover:bg-white/15"
          >
            Load more
          </button>
        </div>
      )}

      {galleryLoading && gallery.length > 0 && (
        <div className="flex justify-center mt-3">
          <span className="text-xs text-white/40">Loading...</span>
        </div>
      )}
    </div>
  )
}
