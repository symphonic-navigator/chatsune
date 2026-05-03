import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { imagesApi, getImageBlob } from '../api'
import type { GeneratedImageDetailDto } from '@/core/api/images'
import { triggerBlobDownload } from '@/core/utils/download'
import { useBackButtonClose } from '@/core/hooks/useBackButtonClose'

interface GalleryLightboxProps {
  imageId: string
  onClose: () => void
  /** Called after the image has been deleted from the backend. */
  onDeleted: () => void | Promise<void>
}

/**
 * Full-viewport lightbox for a gallery image.
 *
 * Fetches the full detail DTO on mount (for metadata) and also fetches the
 * full-size blob via an authenticated GET (Bearer token) for display. Direct
 * <img src="...blob_url"> always 401s because browsers cannot attach
 * Authorization headers to subresource requests.
 *
 * The ObjectURL created from the blob is revoked on unmount to avoid memory leaks.
 * Closes on backdrop click or the Escape key.
 */
export function GalleryLightbox({ imageId, onClose, onDeleted }: GalleryLightboxProps) {
  // Lightbox is rendered only while the parent decides to show it; treat
  // mounted-equals-open and let unmount cleanup close any orphan history.
  useBackButtonClose(true, onClose, 'lightbox-gallery')

  const [detail, setDetail] = useState<GeneratedImageDetailDto | null>(null)
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Fetch metadata.
  useEffect(() => {
    let cancelled = false
    void imagesApi.getImage(imageId).then(
      (d) => { if (!cancelled) setDetail(d) },
      (err) => { if (!cancelled) setError(String(err)) },
    )
    return () => { cancelled = true }
  }, [imageId])

  // Fetch the full-size blob and create a temporary ObjectURL.
  useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null

    async function load() {
      try {
        const fetchedBlob = await getImageBlob(imageId)
        if (cancelled) return
        createdUrl = URL.createObjectURL(fetchedBlob)
        setBlob(fetchedBlob)
        setObjectUrl(createdUrl)
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load image')
        }
      }
    }

    void load()

    return () => {
      cancelled = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
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

  // While the metadata is still loading, render nothing to avoid a brief flash.
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

  // Derive a sensible filename from the image id and mime type.
  function buildFilename(): string {
    const ext = blob?.type === 'image/png' ? 'png' : 'jpg'
    return `image-${imageId.slice(0, 8)}.${ext}`
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
        {objectUrl ? (
          <img
            src={objectUrl}
            alt={detail.prompt}
            className="max-w-full max-h-[70vh] rounded-md object-contain"
          />
        ) : detail.thumbnail_b64 ? (
          /* Low-res preview while the full blob is in flight */
          <img
            src={`data:image/jpeg;base64,${detail.thumbnail_b64}`}
            alt={detail.prompt}
            className="max-w-full max-h-[70vh] rounded-md object-contain opacity-60"
          />
        ) : (
          <div className="w-48 h-48 flex items-center justify-center text-white/40 text-sm">
            Loading…
          </div>
        )}

        <div className="mt-3 w-full text-white/80 text-sm">
          <p className="break-words text-white/80">{detail.prompt}</p>
          <p className="text-xs text-white/50 mt-1">
            {detail.model_id} · {generatedAt}
          </p>

          <div className="mt-3 flex gap-4">
            <button
              type="button"
              disabled={!blob}
              className="text-xs text-white/60 underline whitespace-nowrap hover:text-white/90 transition-colors disabled:opacity-30 disabled:no-underline"
              onClick={(e) => {
                e.stopPropagation()
                if (blob) triggerBlobDownload({ blob, filename: buildFilename() })
              }}
            >
              Download
            </button>
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
