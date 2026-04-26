import type { ImageRefDto } from '@/core/api/images'
import { useState } from 'react'
import { ImageLightbox } from './ImageLightbox'

interface InlineImageBlockProps {
  refs: ImageRefDto[]
  moderatedCount?: number
}

/**
 * Renders generated images inline under an assistant message.
 *
 * Layout rules:
 *   - 1 image:   full-width up to a max height, larger than the row layout.
 *   - 2–4 images: horizontal flex row, equal-ish sizing, wraps on narrow viewports.
 *   - 5+ images:  2-column grid with square aspect-ratio thumbnails.
 *
 * A moderation notice is shown when one or more images were filtered by the
 * provider's content-moderation policy.
 */
export function InlineImageBlock({ refs, moderatedCount = 0 }: InlineImageBlockProps) {
  const [activeId, setActiveId] = useState<string | null>(null)

  // Nothing to render when there are no images and nothing was moderated.
  if (refs.length === 0 && moderatedCount === 0) return null

  const activeRef = activeId !== null ? refs.find((r) => r.id === activeId) : undefined

  const layout: 'single' | 'row' | 'grid' =
    refs.length === 1 ? 'single' : refs.length <= 4 ? 'row' : 'grid'

  return (
    <div className="mt-2">
      {refs.length > 0 && (
        <div
          className={
            layout === 'grid'
              ? 'grid grid-cols-2 gap-2'
              : layout === 'row'
                ? 'flex flex-wrap gap-2'
                : ''
          }
        >
          {refs.map((r) => (
            <button
              key={r.id}
              type="button"
              className="block focus:outline-none rounded-md overflow-hidden"
              onClick={() => setActiveId(r.id)}
              aria-label={`Open image: ${r.prompt.slice(0, 80)}`}
            >
              <img
                src={r.thumbnail_b64 ? `data:image/jpeg;base64,${r.thumbnail_b64}` : r.thumb_url}
                alt={r.prompt}
                className={
                  layout === 'single'
                    ? 'rounded-md max-h-96 max-w-full object-contain'
                    : layout === 'row'
                      ? 'rounded-md max-h-64 object-cover'
                      : 'rounded-md w-full aspect-square object-cover'
                }
                loading="lazy"
              />
            </button>
          ))}
        </div>
      )}

      {moderatedCount > 0 && <ModeratedNote count={moderatedCount} />}

      {activeRef !== undefined && (
        <ImageLightbox imageRef={activeRef} onClose={() => setActiveId(null)} />
      )}
    </div>
  )
}

function ModeratedNote({ count }: { count: number }) {
  return (
    <div className="mt-2 inline-block px-2 py-1 text-xs rounded-md bg-white/5 text-white/50">
      {count === 1
        ? '1 image filtered by content moderation'
        : `${count} images filtered by content moderation`}
    </div>
  )
}
