import { useEffect, useState } from 'react'
import { useImagesStore } from '../store'
import { GalleryLightbox } from './GalleryLightbox'

/**
 * Chronological grid of all images the user has generated.
 *
 * Newest-first, 2 columns on mobile / 4 columns on desktop.
 * Pagination is handled by a "Load more" button — simpler and
 * more reliable than an IntersectionObserver for Phase I.
 */
export function GalleryGrid() {
  const { gallery, galleryLoading, galleryHasMore, loadGalleryFirst, loadGalleryMore, removeFromGallery } =
    useImagesStore()
  const [activeId, setActiveId] = useState<string | null>(null)

  // Seed the gallery on first render. The guard prevents a double-fetch
  // when the component is mounted more than once in the same session.
  useEffect(() => {
    if (gallery.length === 0 && !galleryLoading) {
      void loadGalleryFirst()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="p-4">
      <h2 className="text-[15px] font-semibold text-white/85 mb-4">Generated images</h2>

      {gallery.length === 0 && !galleryLoading && (
        <p className="text-white/60 text-sm">
          No generated images yet. Configure an image-capable connection in the chat cockpit
          and ask the assistant to draw something.
        </p>
      )}

      {galleryLoading && gallery.length === 0 && (
        <p className="text-white/40 text-sm">Loading…</p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {gallery.map((it) => (
          <button
            key={it.id}
            type="button"
            onClick={() => setActiveId(it.id)}
            className="block focus:outline-none rounded-md overflow-hidden group relative"
            aria-label={`Open image: ${it.prompt.slice(0, 80)}`}
          >
            <img
              src={it.thumb_url}
              alt={it.prompt}
              className="rounded-md w-full aspect-square object-cover"
              loading="lazy"
            />
            {/* Hover overlay — truncated prompt */}
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
              <span className="text-xs text-white truncate block">{it.prompt}</span>
            </div>
          </button>
        ))}
      </div>

      {galleryHasMore && (
        <div className="flex justify-center mt-6">
          <button
            type="button"
            disabled={galleryLoading}
            onClick={() => void loadGalleryMore()}
            className="px-4 py-2 rounded-md bg-white/10 hover:bg-white/15 disabled:opacity-50 text-sm text-white/70 transition-colors"
          >
            {galleryLoading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}

      {activeId !== null && (
        <GalleryLightbox
          imageId={activeId}
          onClose={() => setActiveId(null)}
          onDeleted={async () => {
            // removeFromGallery deletes from backend and strips the item from
            // the store in one call — no separate delete API call needed here.
            await removeFromGallery(activeId)
            setActiveId(null)
          }}
        />
      )}
    </div>
  )
}
