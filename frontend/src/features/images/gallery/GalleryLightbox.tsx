import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { imagesApi } from '../api'
import type { GeneratedImageDetailDto } from '@/core/api/images'

interface GalleryLightboxProps {
  imageId: string
  onClose: () => void
  /** Called after the image has been deleted from the backend. */
  onDeleted: () => void | Promise<void>
}

/**
 * Full-viewport lightbox for a gallery image.
 *
 * Fetches the full detail DTO on mount (includes blob_url and config_snapshot),
 * then renders the image with Download and Delete actions.
 * Closes on backdrop click or the Escape key.
 */
export function GalleryLightbox({ imageId, onClose, onDeleted }: GalleryLightboxProps) {
  const [detail, setDetail] = useState<GeneratedImageDetailDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    let cancelled = false
    void imagesApi.getImage(imageId).then(
      (d) => { if (!cancelled) setDetail(d) },
      (err) => { if (!cancelled) setError(String(err)) },
    )
    return () => { cancelled = true }
  }, [imageId])

  // Close on Escape key.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Show a minimal error overlay rather than an empty backdrop.
  if (error) {
    return createPortal(
      <div
        className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
        onClick={onClose}
        aria-modal="true"
        role="dialog"
        aria-label="Image error"
      >
        <div className="bg-white/10 text-white p-4 rounded-md text-sm">
          Failed to load image: {error}
        </div>
      </div>,
      document.body,
    )
  }

  // While loading, render nothing — avoids a brief flash of an empty overlay.
  if (!detail) return null

  async function handleDelete() {
    if (!confirm('Delete this image? This cannot be undone.')) return
    setDeleting(true)
    try {
      await onDeleted()
    } finally {
      setDeleting(false)
    }
  }

  const generatedAt = new Date(detail.generated_at).toLocaleString('en-GB')

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center"
      onClick={onClose}
      aria-modal="true"
      role="dialog"
      aria-label={`Image: ${detail.prompt}`}
    >
      <div
        className="max-w-[90vw] max-h-[90vh] p-4 flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={detail.blob_url}
          alt={detail.prompt}
          className="max-w-full max-h-[70vh] rounded-md object-contain"
        />

        <div className="mt-3 w-full text-white/80 text-sm">
          <p className="break-words text-white/80">{detail.prompt}</p>
          <p className="text-xs text-white/50 mt-1">
            {detail.model_id} · {generatedAt}
          </p>

          <div className="mt-3 flex gap-4">
            <a
              href={detail.blob_url}
              download
              className="text-xs text-white/60 underline whitespace-nowrap hover:text-white/90 transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              Download
            </a>
            <button
              type="button"
              disabled={deleting}
              onClick={handleDelete}
              className="text-xs text-red-400 underline disabled:opacity-50 hover:text-red-300 transition-colors"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
