import { useAvatarSrc } from '../../../core/hooks/useAvatarSrc'
import type { ProfileCrop } from '../../../core/types/persona'

/** Crop-circle diameter used in the AvatarCropModal canvas. Must match the modal constant. */
const CROP_DIAMETER = 220
/** Canvas size used in the AvatarCropModal. Must match the modal constant. */
const CANVAS_SIZE = 280

interface CroppedAvatarProps {
  personaId: string
  updatedAt?: string
  crop: ProfileCrop | null
  size: number
  alt: string
  className?: string
}

/**
 * Displays a persona avatar with virtual cropping via CSS background-image.
 *
 * The crop parameters describe how the image was positioned on the modal canvas:
 *   - zoom: scale factor applied to the image's natural dimensions
 *   - x, y: pixel offset from centre on the 280px canvas
 *   - width, height: the image's natural dimensions (after normalisation)
 *
 * We reproduce the crop circle's view by computing the equivalent
 * background-size and background-position for the target display size.
 */
export function CroppedAvatar({ personaId, updatedAt, crop, size, alt, className = '' }: CroppedAvatarProps) {
  const src = useAvatarSrc(personaId, true, updatedAt)

  if (!src) {
    return (
      <div
        className={`rounded-full flex-shrink-0 ${className}`}
        style={{ width: size, height: size, background: '#1a1a2e' }}
      />
    )
  }

  if (!crop || (crop.width === 0 && crop.height === 0)) {
    return (
      <div
        role="img"
        aria-label={alt}
        className={`rounded-full flex-shrink-0 ${className}`}
        style={{
          width: size,
          height: size,
          backgroundImage: `url("${src}")`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      />
    )
  }

  // Scale factor from modal crop-circle coordinate space to display size
  const scale = size / CROP_DIAMETER

  // Image dimensions as they appeared on the canvas
  const canvasImgW = crop.width * crop.zoom
  const canvasImgH = crop.height * crop.zoom

  // Image top-left position on the canvas
  const canvasImgX = (CANVAS_SIZE / 2) - (canvasImgW / 2) + crop.x
  const canvasImgY = (CANVAS_SIZE / 2) - (canvasImgH / 2) + crop.y

  // Crop circle bounding box top-left on the canvas
  const cropBoxX = (CANVAS_SIZE - CROP_DIAMETER) / 2
  const cropBoxY = (CANVAS_SIZE - CROP_DIAMETER) / 2

  // Image position relative to the crop circle bounding box
  const relX = canvasImgX - cropBoxX
  const relY = canvasImgY - cropBoxY

  // Scale everything to the display size
  const bgW = canvasImgW * scale
  const bgH = canvasImgH * scale
  const bgX = relX * scale
  const bgY = relY * scale

  return (
    <div
      role="img"
      aria-label={alt}
      className={`rounded-full flex-shrink-0 ${className}`}
      style={{
        width: size,
        height: size,
        backgroundImage: `url("${src}")`,
        backgroundSize: `${bgW}px ${bgH}px`,
        backgroundPosition: `${bgX}px ${bgY}px`,
        backgroundRepeat: 'no-repeat',
      }}
    />
  )
}
