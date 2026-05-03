import type { ImageRefDto } from '@/core/api/images'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { getImageBlob } from '../api'
import { triggerBlobDownload } from '@/core/utils/download'
import { useBackButtonClose } from '@/core/hooks/useBackButtonClose'

interface ImageLightboxProps {
  imageRef: ImageRefDto
  onClose: () => void
}

/**
 * Full-viewport lightbox for a single generated image.
 *
 * Rendered via a React portal so it sits above all other UI regardless of
 * stacking context. Closes on backdrop click or the Escape key.
 *
 * The full-size image is loaded via an authenticated fetch (Bearer token) and
 * displayed via a temporary ObjectURL — direct <img src="/api/images/{id}/blob">
 * always 401s because browsers cannot attach Authorization headers to subresource
 * requests. The ObjectURL is revoked on unmount to avoid memory leaks.
 *
 * While the blob is loading the thumbnail_b64 (if present) is shown as a low-res
 * preview so the user sees something immediately.
 */
export function ImageLightbox({ imageRef, onClose }: ImageLightboxProps) {
  // Lightbox is rendered only while the parent decides to show it; treat
  // mounted-equals-open and let unmount cleanup close any orphan history.
  useBackButtonClose(true, onClose, 'lightbox-chat')

  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Close on Escape key.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Fetch the full-size blob and create a temporary ObjectURL.
  useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null

    async function load() {
      try {
        const fetchedBlob = await getImageBlob(imageRef.id)
        if (cancelled) return
        createdUrl = URL.createObjectURL(fetchedBlob)
        setBlob(fetchedBlob)
        setObjectUrl(createdUrl)
      } catch (e) {
        if (!cancelled) {
          setLoadError(e instanceof Error ? e.message : 'Failed to load image')
        }
      }
    }

    void load()

    return () => {
      cancelled = true
      if (createdUrl) URL.revokeObjectURL(createdUrl)
    }
  }, [imageRef.id])

  // Derive a sensible filename from the image id and mime type.
  function buildFilename(): string {
    const ext = blob?.type === 'image/png' ? 'png' : 'jpg'
    return `image-${imageRef.id.slice(0, 8)}.${ext}`
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center"
      onClick={onClose}
      aria-modal="true"
      role="dialog"
      aria-label={`Image: ${imageRef.prompt}`}
    >
      <div
        className="max-w-[90vw] max-h-[90vh] p-4 flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        {loadError ? (
          <div className="text-white/70 text-sm px-4 py-6">{loadError}</div>
        ) : objectUrl ? (
          <img
            src={objectUrl}
            alt={imageRef.prompt}
            className="max-w-full max-h-[80vh] rounded-md object-contain"
          />
        ) : imageRef.thumbnail_b64 ? (
          /* Low-res preview while the full blob is in flight */
          <img
            src={`data:image/jpeg;base64,${imageRef.thumbnail_b64}`}
            alt={imageRef.prompt}
            className="max-w-full max-h-[80vh] rounded-md object-contain opacity-60"
          />
        ) : (
          <div className="w-48 h-48 flex items-center justify-center text-white/40 text-sm">
            Loading…
          </div>
        )}

        <div className="mt-3 w-full flex justify-between items-center text-white/80 text-sm gap-3">
          <span
            className="truncate flex-1 max-w-[60ch] text-white/60 text-xs"
            title={imageRef.prompt}
          >
            {imageRef.prompt}
          </span>
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
        </div>
      </div>
    </div>,
    document.body,
  )
}
