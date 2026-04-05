import { useCallback, useEffect, useRef, useState } from 'react'

interface AvatarCropModalProps {
  isOpen: boolean
  onClose: () => void
  onSave: (croppedBlob: Blob) => void | Promise<void>
  currentImageUrl?: string | null
  accentColour?: string
}

const CANVAS_SIZE = 280
const CROP_DIAMETER = 220
const CROP_RADIUS = CROP_DIAMETER / 2
const OUTPUT_SIZE = 256
const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5 MB
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const MIN_ZOOM = 0.5
const MAX_ZOOM = 3

export function AvatarCropModal({
  isOpen,
  onClose,
  onSave,
  currentImageUrl,
  accentColour = '#c8a44e',
}: AvatarCropModalProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [image, setImage] = useState<HTMLImageElement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load current image on open
  useEffect(() => {
    if (!isOpen) return
    setError(null)
    setSaving(false)

    if (currentImageUrl) {
      const img = new Image()
      img.crossOrigin = 'anonymous'
      img.onload = () => {
        setImage(img)
        const initialZoom = calcInitialZoom(img)
        setZoom(initialZoom)
        setOffset({ x: 0, y: 0 })
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
  }, [isOpen, currentImageUrl])

  // Calculate initial zoom so shortest side fills crop circle
  function calcInitialZoom(img: HTMLImageElement): number {
    const shortSide = Math.min(img.naturalWidth, img.naturalHeight)
    if (shortSide === 0) return 1
    return CROP_DIAMETER / shortSide
  }

  // Draw canvas
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const cx = CANVAS_SIZE / 2
    const cy = CANVAS_SIZE / 2

    // Clear
    ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

    // Draw image
    if (image) {
      const w = image.naturalWidth * zoom
      const h = image.naturalHeight * zoom
      const x = cx - w / 2 + offset.x
      const y = cy - h / 2 + offset.y
      ctx.drawImage(image, x, y, w, h)
    }

    // Draw dark overlay with circular cutout
    ctx.save()
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)'
    ctx.beginPath()
    // Outer rect (full canvas)
    ctx.rect(0, 0, CANVAS_SIZE, CANVAS_SIZE)
    // Inner circle (cutout) — drawn counter-clockwise to create hole
    ctx.arc(cx, cy, CROP_RADIUS, 0, Math.PI * 2, true)
    ctx.fill()

    // Circle border
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(cx, cy, CROP_RADIUS, 0, Math.PI * 2)
    ctx.stroke()
    ctx.restore()
  }, [image, zoom, offset])

  // Redraw on state change
  useEffect(() => {
    draw()
  }, [draw])

  // File selection
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
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

    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      setImage(img)
      const initialZoom = calcInitialZoom(img)
      setZoom(initialZoom)
      setOffset({ x: 0, y: 0 })
    }
    img.onerror = () => {
      setError('Failed to load image.')
      URL.revokeObjectURL(url)
    }
    img.src = url

    // Reset input so re-selecting the same file triggers onChange
    e.target.value = ''
  }

  // Mouse drag handlers
  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!image) return
    setIsDragging(true)
    setDragStart({ x: e.clientX - offset.x, y: e.clientY - offset.y })
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!isDragging) return
    setOffset({
      x: e.clientX - dragStart.x,
      y: e.clientY - dragStart.y,
    })
  }

  function handleMouseUp() {
    setIsDragging(false)
  }

  // Touch drag handlers
  function handleTouchStart(e: React.TouchEvent<HTMLCanvasElement>) {
    if (!image || e.touches.length !== 1) return
    const touch = e.touches[0]
    setIsDragging(true)
    setDragStart({ x: touch.clientX - offset.x, y: touch.clientY - offset.y })
  }

  function handleTouchMove(e: React.TouchEvent<HTMLCanvasElement>) {
    if (!isDragging || e.touches.length !== 1) return
    e.preventDefault()
    const touch = e.touches[0]
    setOffset({
      x: touch.clientX - dragStart.x,
      y: touch.clientY - dragStart.y,
    })
  }

  function handleTouchEnd() {
    setIsDragging(false)
  }

  // Crop and export
  async function handleSave() {
    if (!image) return
    setSaving(true)

    try {
      const offscreen = document.createElement('canvas')
      offscreen.width = OUTPUT_SIZE
      offscreen.height = OUTPUT_SIZE
      const ctx = offscreen.getContext('2d')
      if (!ctx) return

      const outRadius = OUTPUT_SIZE / 2

      // Clip to circle
      ctx.beginPath()
      ctx.arc(outRadius, outRadius, outRadius, 0, Math.PI * 2)
      ctx.closePath()
      ctx.clip()

      // Scale factor from canvas crop area to output size
      const scale = OUTPUT_SIZE / CROP_DIAMETER

      // Calculate where the image sits relative to the crop circle centre
      const cx = CANVAS_SIZE / 2
      const cy = CANVAS_SIZE / 2
      const imgW = image.naturalWidth * zoom
      const imgH = image.naturalHeight * zoom
      const imgX = cx - imgW / 2 + offset.x
      const imgY = cy - imgH / 2 + offset.y

      // Relative to crop circle top-left
      const cropLeft = cx - CROP_RADIUS
      const cropTop = cy - CROP_RADIUS
      const relX = (imgX - cropLeft) * scale
      const relY = (imgY - cropTop) * scale
      const drawW = imgW * scale
      const drawH = imgH * scale

      ctx.drawImage(image, relX, relY, drawW, drawH)

      const blob = await new Promise<Blob | null>((resolve) =>
        offscreen.toBlob(resolve, 'image/png'),
      )

      if (blob) {
        await onSave(blob)
      }
    } finally {
      setSaving(false)
    }
  }

  // Escape key
  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const borderColour = accentColour + '26' // 15% opacity

  return (
    <>
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/60 z-30"
        onClick={onClose}
        aria-hidden
      />

      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Profile Picture"
        className="absolute z-40 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col rounded-xl shadow-2xl overflow-hidden"
        style={{
          backgroundColor: '#13101e',
          border: `1px solid ${borderColour}`,
          width: 340,
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/6">
          <span className="font-mono text-[13px] font-semibold text-white/80">
            Profile Picture
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col items-center gap-3 px-5 py-4">
          {/* Canvas */}
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
            style={{
              width: CANVAS_SIZE,
              height: CANVAS_SIZE,
              cursor: image ? (isDragging ? 'grabbing' : 'grab') : 'default',
              touchAction: 'none',
            }}
          />

          {/* Zoom slider */}
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

          {/* Error message */}
          {error && (
            <p className="font-mono text-[11px] text-red-400 text-center">
              {error}
            </p>
          )}

          {/* File picker */}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            onChange={handleFileSelect}
            className="hidden"
          />
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
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-white/6">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded text-[12px] font-mono text-white/50 bg-white/6 hover:bg-white/10 hover:text-white/70 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!image || saving}
            className="px-4 py-1.5 rounded text-[12px] font-mono font-semibold transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              backgroundColor: image && !saving ? accentColour : undefined,
              color: image && !saving ? '#13101e' : undefined,
            }}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </>
  )
}
