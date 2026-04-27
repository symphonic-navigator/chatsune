import { useEffect, useRef } from 'react'
import type { VisualiserStyle } from '../stores/voiceSettingsStore'
import { drawVisualiserFrame } from '../infrastructure/visualiserRenderers'
import {
  simulateAmplitude,
  simulateFrequencyBins,
} from '../infrastructure/visualiserSpeechSimulator'

const MAX_HEIGHT_FRACTION = 0.55  // preview is short — bars need to be visibly tall
const DEFAULT_HEX = '#8C76D7'

interface Props {
  style: VisualiserStyle
  opacity: number
  barCount: number
  enabled: boolean
  /** Active persona's chakra colour. Defaults to crown if not provided. */
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

export function VoiceVisualiserPreview({
  style,
  opacity,
  barCount,
  enabled,
  personaColourHex = DEFAULT_HEX,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const c = canvasRef.current
      if (c) c.getContext('2d')?.clearRect(0, 0, c.width, c.height)
      return
    }

    let stopped = false
    const tick = (now: number) => {
      if (stopped) return
      const c = canvasRef.current
      if (!c) { rafRef.current = requestAnimationFrame(tick); return }
      const w = c.clientWidth
      const h = c.clientHeight
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h }
      const ctx = c.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, w, h)

      const t = now / 1000
      const ampl = simulateAmplitude(t)
      const bins = simulateFrequencyBins(t, ampl, barCount)
      const rgb = hexToRgb(personaColourHex)
      const rgbLight = brighten(rgb)
      drawVisualiserFrame(style, ctx, h, bins, {
        rgb,
        rgbLight,
        opacity,
        maxHeightFraction: MAX_HEIGHT_FRACTION,
      }, { chatview: { x: w * 0.05, w: w * 0.9 }, textColumn: { x: w * 0.05, w: w * 0.9 } })
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      stopped = true
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [style, opacity, barCount, enabled, personaColourHex])

  return (
    <div
      aria-hidden
      className="relative w-full h-[120px] rounded-md overflow-hidden bg-[#0a0810] border border-white/10"
    >
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
      {!enabled && (
        <div className="absolute inset-0 flex items-center justify-center text-white/40 font-mono text-xs uppercase tracking-wider">
          Aus
        </div>
      )}
    </div>
  )
}
