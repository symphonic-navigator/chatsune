import type { ImageRefDto } from '@/core/api/images'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

interface ImageLightboxProps {
  imageRef: ImageRefDto
  onClose: () => void
}

/**
 * Full-viewport lightbox for a single generated image.
 *
 * Rendered via a React portal so it sits above all other UI regardless of
 * stacking context. Closes on backdrop click or the Escape key.
 */
export function ImageLightbox({ imageRef, onClose }: ImageLightboxProps) {
  // Close on Escape key.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

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
        <img
          src={imageRef.blob_url}
          alt={imageRef.prompt}
          className="max-w-full max-h-[80vh] rounded-md object-contain"
        />
        <div className="mt-3 w-full flex justify-between items-center text-white/80 text-sm gap-3">
          <span
            className="truncate flex-1 max-w-[60ch] text-white/60 text-xs"
            title={imageRef.prompt}
          >
            {imageRef.prompt}
          </span>
          <a
            href={imageRef.blob_url}
            download
            className="text-xs text-white/60 underline whitespace-nowrap hover:text-white/90 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            Download
          </a>
        </div>
      </div>
    </div>,
    document.body,
  )
}
