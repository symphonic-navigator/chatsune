import { useEffect, useRef } from 'react'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserLayoutStore } from '../stores/visualiserLayoutStore'
import { usePauseRedemptionStore } from '../stores/pauseRedemptionStore'
import { drawPieFrame } from '../infrastructure/pieRenderers'

const DEFAULT_HEX = '#8C76D7'
const PIE_DIAMETER_RATIO = 0.18   // ~18 % of the chatview width, capped.
const PIE_DIAMETER_MAX = 140
const PIE_DIAMETER_MIN = 72

interface Props {
  /** Active persona's accent colour hex (e.g. '#d4a857'). */
  personaColourHex?: string
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ]
}

function brighten([r, g, b]: [number, number, number]): [number, number, number] {
  return [Math.min(255, r + 40), Math.min(255, g + 40), Math.min(255, b + 40)]
}

export function VoiceCountdownPie({ personaColourHex = DEFAULT_HEX }: Props) {
  const active = usePauseRedemptionStore((s) => s.active)
  const startedAt = usePauseRedemptionStore((s) => s.startedAt)
  const windowMs = usePauseRedemptionStore((s) => s.windowMs)

  const style = useVoiceSettingsStore((s) => s.visualisation.style)
  const opacity = useVoiceSettingsStore((s) => s.visualisation.opacity)
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)

  const chatview = useVisualiserLayoutStore((s) => s.chatview)
  const textColumn = useVisualiserLayoutStore((s) => s.textColumn)
  // Use the textColumn rect to match the visualiser's horizontal centre (spec §3.2).
  // Fall back to chatview when textColumn is not yet measured (e.g. on first render
  // or in tests that only seed chatview).
  const layout = textColumn ?? chatview

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!active || !enabled || !layout || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio ?? 1
    const rgb = hexToRgb(personaColourHex)
    const rgbLight = brighten(rgb)

    const tick = () => {
      // Use getBoundingClientRect rather than window.innerWidth/innerHeight:
      // under `body { zoom: --ui-scale }` those values are pre-zoom CSS pixels
      // while layout.x comes from getBoundingClientRect() (post-zoom). Using
      // getBoundingClientRect here keeps both coordinate spaces consistent.
      const rect = canvas.getBoundingClientRect()
      const cssW = rect.width
      const cssH = rect.height
      const wPx = Math.round(cssW * dpr)
      const hPx = Math.round(cssH * dpr)
      if (canvas.width !== wPx || canvas.height !== hPx) {
        canvas.width = wPx
        canvas.height = hPx
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      }

      // layout.x and layout.w are post-zoom CSS pixels (getBoundingClientRect
      // in useReportBounds); cssH from getBoundingClientRect above is also
      // post-zoom — both are in the same coordinate space.
      const cx = layout.x + layout.w / 2
      const cy = cssH / 2

      const diameter = Math.max(
        PIE_DIAMETER_MIN,
        Math.min(PIE_DIAMETER_MAX, Math.min(layout.w, cssH) * PIE_DIAMETER_RATIO),
      )
      const radius = diameter / 2

      ctx.clearRect(0, 0, cssW, cssH)
      const elapsed = startedAt === null ? 0 : performance.now() - startedAt
      const remainingFraction = windowMs > 0
        ? Math.max(0, 1 - elapsed / windowMs)
        : 0
      drawPieFrame(style, ctx, {
        cx, cy, radius,
        remainingFraction,
        rgb, rgbLight, opacity,
      })
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [active, enabled, layout, textColumn, chatview, startedAt, windowMs, style, opacity, personaColourHex])

  if (!active || !enabled || !layout) return null

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: 'fixed',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 1,
      }}
    />
  )
}
