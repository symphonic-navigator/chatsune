import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { ProfileCrop } from '../../../core/types/persona'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { Sheet } from '../../../core/components/Sheet'

interface AvatarCropModalProps {
  isOpen: boolean
  onClose: () => void
  /** Called with the normalised full image blob + crop params. If imageChanged is false, only crop was adjusted. */
  onSave: (blob: Blob | null, crop: ProfileCrop) => void | Promise<void>
  onRemove?: () => void | Promise<void>
  hasExisting?: boolean
  currentImageUrl?: string | null
  /** Existing crop params to restore when re-editing. */
  initialCrop?: ProfileCrop | null
  accentColour?: string
}

export const CROP_MODAL_CANVAS_SIZE = 280
export const CROP_MODAL_CROP_DIAMETER = 220

const CANVAS_SIZE = CROP_MODAL_CANVAS_SIZE
const CROP_DIAMETER = CROP_MODAL_CROP_DIAMETER
const CROP_RADIUS = CROP_DIAMETER / 2
const NORMALISE_MAX = 1024
const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5 MB
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const MIN_ZOOM = 0.1
const MAX_ZOOM = 3

export function AvatarCropModal({
  isOpen,
  onClose,
  onSave,
  onRemove,
  hasExisting,
  currentImageUrl,
  initialCrop,
  accentColour = '#c8a44e',
}: AvatarCropModalProps) {
  const [removing, setRemoving] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useFocusTrap(dialogRef, isOpen)

  const [image, setImage] = useState<HTMLImageElement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Track whether user picked a new file (needs upload) or just adjusted crop
  const [imageChanged, setImageChanged] = useState(false)
  // Store the raw file blob for upload (normalised)
  const pendingBlob = useRef<Blob | null>(null)

  // Load current image on open, restore crop params
  useEffect(() => {
    if (!isOpen) return
    setError(null)
    setSaving(false)
    setImageChanged(false)
    pendingBlob.current = null

    if (currentImageUrl) {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        setImage(img)
        if (initialCrop && initialCrop.width > 0) {
          // Restore previous crop state
          setZoom(initialCrop.zoom)
          setOffset({ x: initialCrop.x, y: initialCrop.y })
        } else {
          const z = calcInitialZoom(img)
          setZoom(z)
          setOffset({ x: 0, y: 0 })
        }
      }
      img.onerror = () => {
        setImage(null)
      }
      img.src = currentImageUrl
    } else {
      setImage(null)
      setZoom(1)
      setOffset({ x: 0, y: 0 })
    }
  }, [isOpen, currentImageUrl, initialCrop])

  function calcInitialZoom(img: HTMLImageElement): number {
    const shortSide = Math.min(img.naturalWidth, img.naturalHeight)
    if (shortSide === 0) return 1
    return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, CROP_DIAMETER / shortSide))
  }

  // Draw canvas
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const cx = CANVAS_SIZE / 2
    const cy = CANVAS_SIZE / 2

    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

    if (image) {
      const w = image.naturalWidth * zoom
      const h = image.naturalHeight * zoom
      const x = cx - w / 2 + offset.x
      const y = cy - h / 2 + offset.y
      ctx.drawImage(image, x, y, w, h)
    }

    // Dark overlay with circular cutout
    ctx.save()
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)'
    ctx.beginPath()
    ctx.rect(0, 0, CANVAS_SIZE, CANVAS_SIZE)
    ctx.arc(cx, cy, CROP_RADIUS, 0, Math.PI * 2, true)
    ctx.fill()

    ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(cx, cy, CROP_RADIUS, 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
  }, [image, zoom, offset])

  useEffect(() => { draw() }, [draw])

  /** Normalise image to max NORMALISE_MAX px on longest side, return as PNG blob + loaded Image. */
  async function normaliseImage(file: File): Promise<{ blob: Blob; img: HTMLImageElement }> {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file)
      const img = new Image()
      img.onload = () => {
        const { naturalWidth: w, naturalHeight: h } = img
        let targetW = w
        let targetH = h
        if (Math.max(w, h) > NORMALISE_MAX) {
          if (w >= h) {
            targetW = NORMALISE_MAX
            targetH = Math.round(h * (NORMALISE_MAX / w))
          } else {
            targetH = NORMALISE_MAX
            targetW = Math.round(w * (NORMALISE_MAX / h))
          }
        }

        const canvas = document.createElement('canvas')
        canvas.width = targetW
        canvas.height = targetH
        const ctx = canvas.getContext('2d')!
        ctx.drawImage(img, 0, 0, targetW, targetH)

        canvas.toBlob((blob) => {
          URL.revokeObjectURL(url)
          if (!blob) { reject(new Error('Failed to normalise')); return }
          // Create a new Image from the normalised blob so naturalWidth/Height are correct
          const normUrl = URL.createObjectURL(blob)
          const normImg = new Image()
          normImg.onload = () => resolve({ blob, img: normImg })
          normImg.onerror = () => { URL.revokeObjectURL(normUrl); reject(new Error('Failed to load normalised')) }
          normImg.src = normUrl
        }, 'image/png')
      }
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Failed to load')) }
      img.src = url
    })
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    setError(null)
    const file = e.target.files?.[0]
    if (!file) return

    if (!ACCEPTED_TYPES.includes(file.type)) {
      setError('Unsupported format. Use JPEG, PNG, WebP, or GIF.')
      return
    }
    if (file.size > MAX_FILE_SIZE) {
      setError('File exceeds 5 MB limit.')
      return
    }

    try {
      const { blob, img } = await normaliseImage(file)
      pendingBlob.current = blob
      setImage(img)
      setImageChanged(true)
      const z = calcInitialZoom(img)
      setZoom(z)
      setOffset({ x: 0, y: 0 })
    } catch {
      setError('Failed to process image.')
    }

    e.target.value = ''
  }

  // Mouse drag
  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!image) return
    setIsDragging(true)
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
  }
  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!isDragging) return
    setOffset({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y })
  }
  function handleMouseUp() { setIsDragging(false) }

  // Touch drag
  function handleTouchStart(e: React.TouchEvent<HTMLCanvasElement>) {
    if (!image || e.touches.length !== 1) return
    const t = e.touches[0]
    setIsDragging(true)
    setDragStart({ x: t.clientX - offset.x, y: t.clientY - offset.y })
  }
  function handleTouchMove(e: React.TouchEvent<HTMLCanvasElement>) {
    if (!isDragging || e.touches.length !== 1) return
    e.preventDefault()
    const t = e.touches[0]
    setOffset({ x: t.clientX - dragStart.x, y: t.clientY - dragStart.y })
  }
  function handleTouchEnd() { setIsDragging(false) }

  async function handleSave() {
    if (!image) return
    setSaving(true)

    try {
      const crop: ProfileCrop = {
        x: offset.x,
        y: offset.y,
        zoom,
        width: image.naturalWidth,
        height: image.naturalHeight,
      }
      // If a new file was picked, send the blob; otherwise null (crop-only update)
      await onSave(imageChanged ? pendingBlob.current : null, crop)
    } finally {
      setSaving(false)
    }
  }

  // Esc handling is provided by <Sheet>.

  const borderColour = accentColour + '26'

  return (
    <Sheet isOpen={isOpen} onClose={onClose} size="sm" ariaLabel="Profile picture">
      <div
        ref={dialogRef}
        aria-labelledby={titleId}
        className="flex flex-1 flex-col overflow-y-auto lg:flex-none lg:overflow-visible"
        style={{ backgroundColor: '#13101e', border: `1px solid ${borderColour}` }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/6">
          <span id={titleId} className="font-mono text-[13px] font-semibold text-white/80">Profile Picture</span>
          <button type="button" onClick={onClose} aria-label="Close" className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors cursor-pointer">
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col items-center gap-3 px-5 py-4">
          <canvas
            ref={canvasRef}
            width={CANVAS_SIZE}
            height={CANVAS_SIZE}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
            className="rounded border border-white/10"
            style={{ width: CANVAS_SIZE, height: CANVAS_SIZE, cursor: image ? (isDragging ? 'grabbing' : 'grab') : 'default', touchAction: 'none' }}
          />

          {image && (
            <div className="flex items-center gap-2 w-full px-1">
              <span className="font-mono text-[11px] text-white/40 select-none">-</span>
              <input
                type="range"
                min={MIN_ZOOM}
                max={MAX_ZOOM}
                step={0.01}
                value={zoom}
                onChange={(e) => setZoom(parseFloat(e.target.value))}
                className="flex-1 h-1 appearance-none rounded-full cursor-pointer"
                style={{
                  background: `linear-gradient(to right, ${accentColour} ${((zoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM)) * 100}%, rgba(255,255,255,0.12) ${((zoom - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM)) * 100}%)`,
                  accentColor: accentColour,
                }}
              />
              <span className="font-mono text-[11px] text-white/40 select-none">+</span>
            </div>
          )}

          {error && <p className="font-mono text-[11px] text-red-400 text-center">{error}</p>}

          <input ref={fileInputRef} type="file" accept={ACCEPTED_TYPES.join(',')} onChange={handleFileSelect} className="hidden" />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-mono text-white/60 bg-white/6 hover:bg-white/10 hover:text-white/80 transition-colors cursor-pointer"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            Choose Image
          </button>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-5 py-3 border-t border-white/6">
          {onRemove && hasExisting && (
            <button
              type="button"
              disabled={removing}
              onClick={async () => { setRemoving(true); try { await onRemove() } finally { setRemoving(false) } }}
              className="px-3 py-1.5 rounded text-[12px] font-mono text-red-400/70 bg-red-400/8 hover:bg-red-400/15 hover:text-red-400 transition-colors cursor-pointer disabled:opacity-40"
            >
              {removing ? 'Removing...' : 'Remove'}
            </button>
          )}
          <div className="flex-1" />
          <button type="button" onClick={onClose} className="px-3 py-1.5 rounded text-[12px] font-mono text-white/50 bg-white/6 hover:bg-white/10 hover:text-white/70 transition-colors cursor-pointer">
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!image || saving}
            className="px-4 py-1.5 rounded text-[12px] font-mono font-semibold transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ backgroundColor: image && !saving ? accentColour : undefined, color: image && !saving ? '#13101e' : undefined }}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
