import { useEffect, useRef } from 'react'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserPauseStore } from '../stores/visualiserPauseStore'
import { useVisualiserLayoutStore } from '../stores/visualiserLayoutStore'
import { useTtsFrequencyData } from '../infrastructure/useTtsFrequencyData'
import { drawVisualiserFrame, drawTranscriptionDots } from '../infrastructure/visualiserRenderers'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { fillNoiseBins } from '../infrastructure/visualiserNoise'
import { useTtsExpected } from '../infrastructure/useTtsExpected'
import { useVoicePipeline } from '../stores/voicePipelineStore'

const MAX_HEIGHT_FRACTION = 0.28
const FADE_RATE = 0.05
const DEFAULT_HEX = '#8C76D7'

interface Props {
  /** Active persona's chakra colour as a hex string (e.g. '#8C76D7'). */
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

export function VoiceVisualiser({ personaColourHex = DEFAULT_HEX }: Props) {
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)
  const style = useVoiceSettingsStore((s) => s.visualisation.style)
  const opacity = useVoiceSettingsStore((s) => s.visualisation.opacity)
  const barCount = useVoiceSettingsStore((s) => s.visualisation.barCount)

  const paused = useVisualiserPauseStore((s) => s.paused)

  const chatview = useVisualiserLayoutStore((s) => s.chatview)
  const textColumn = useVisualiserLayoutStore((s) => s.textColumn)

  const phase = useVoicePipeline((s) => s.state.phase)

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const activeRef = useRef(0)
  const dotsActiveRef = useRef(0)
  const reducedMotionRef = useRef(false)
  const frozenBinsRef = useRef<Float32Array | null>(null)

  // Buffer used when the noise branch is the data source.
  // Stable across renders; resized when barCount changes.
  const noiseBufferRef = useRef<Float32Array>(new Float32Array(barCount))
  if (noiseBufferRef.current.length !== barCount) {
    noiseBufferRef.current = new Float32Array(barCount)
  }

  const accessors = useTtsFrequencyData(barCount)

  // Forward declaration so the edge callback can call it. The actual
  // function is assigned inside the effect below; we just need a stable
  // ref to wrap it.
  const resumeRafRef = useRef<(() => void) | null>(null)

  const ttsExpected = useTtsExpected({
    onTrueEdge: () => {
      resumeRafRef.current?.()
    },
  })

  // Reduced-motion subscription. Honours OS-level preference live.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotionRef.current = mq.matches
    const listener = () => { reducedMotionRef.current = mq.matches }
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  useEffect(() => {
    if (!enabled || !chatview || !textColumn) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const c = canvasRef.current
      if (c) c.getContext('2d')?.clearRect(0, 0, c.width, c.height)
      activeRef.current = 0
      return
    }

    let stopped = false

    const tick = () => {
      if (stopped) return
      const c = canvasRef.current
      if (!c) { rafRef.current = requestAnimationFrame(tick); return }

      // DPR clamped to 1 — soft decorative shapes, saves ~4× memory at 4K.
      // Use getBoundingClientRect rather than clientWidth/Height: under
      // body { zoom: --ui-scale } the canvas is position: fixed and
      // clientWidth returns pre-zoom CSS pixels while the canvas is
      // visually rendered at post-zoom size. Our bounds are also post-zoom
      // (getBoundingClientRect everywhere), so the buffer must match.
      const rect = c.getBoundingClientRect()
      const w = Math.round(rect.width)
      const h = Math.round(rect.height)
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h }

      const geometry = { chatview, textColumn }

      const ctx = c.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, w, h)

      if (reducedMotionRef.current) {
        rafRef.current = requestAnimationFrame(tick)
        return
      }

      // Spec invariant: paused only becomes true while audio is actually
      // playing. The HitStrip upstream gates the pause toggle on playback
      // state, so we never enter this branch during the noise (expected
      // but no-audio) phase. If that invariant ever lapses, the snapshot
      // below would freeze a zero-filled buffer for sessions that never
      // had audio, which renders as a blank canvas — not a crash, but
      // visually wrong; revisit the upstream guard rather than adding a
      // defensive branch here.
      if (paused) {
        const bins = accessors.getBins()
        if (!frozenBinsRef.current) {
          frozenBinsRef.current = bins ? bins.slice() : new Float32Array(barCount)
        }
        const t = performance.now() / 1000
        const breath = 0.8 + 0.2 * Math.sin((t * 2 * Math.PI) / 2.5)  // 0.6..1.0
        const rgb = hexToRgb(personaColourHex)
        const rgbLight = brighten(rgb)
        drawVisualiserFrame(style, ctx, h, frozenBinsRef.current, {
          rgb,
          rgbLight,
          opacity: opacity * breath,
          maxHeightFraction: MAX_HEIGHT_FRACTION,
        }, geometry)
        rafRef.current = requestAnimationFrame(tick)
        return
      }

      // Not paused — clear any stale snapshot.
      frozenBinsRef.current = null

      const playing = accessors.isActive()
      const expected = ttsExpected()
      const visible = playing || expected
      const target = visible ? 1 : 0
      activeRef.current += (target - activeRef.current) * FADE_RATE

      // Always advance the dots fade so transitions stay smooth even when
      // the bars branch is the one rendering this frame. Bars and dots are
      // mutually exclusive at the render level (priority bars > dots), but
      // both fades must keep tracking the phase so the visual handover
      // transcribing → speaking does not freeze the dots at non-zero.
      const transcribing = phase === 'transcribing'
      const dotsTarget = transcribing ? 1 : 0
      dotsActiveRef.current += (dotsTarget - dotsActiveRef.current) * FADE_RATE

      if (activeRef.current > 0.005) {
        let bins: Float32Array | null = null
        if (playing) {
          bins = accessors.getBins()
        } else if (expected) {
          fillNoiseBins(noiseBufferRef.current, performance.now() / 1000)
          bins = noiseBufferRef.current
        }
        if (bins) {
          const rgb = hexToRgb(personaColourHex)
          const rgbLight = brighten(rgb)
          drawVisualiserFrame(style, ctx, h, bins, {
            rgb,
            rgbLight,
            opacity: opacity * activeRef.current,
            maxHeightFraction: MAX_HEIGHT_FRACTION,
          }, geometry)
        }
        rafRef.current = requestAnimationFrame(tick)
      } else if (visible) {
        // Visible but still ramping in — keep the loop running.
        rafRef.current = requestAnimationFrame(tick)
      } else if (dotsActiveRef.current > 0.005) {
        const rgb = hexToRgb(personaColourHex)
        const rgbLight = brighten(rgb)
        drawTranscriptionDots(style, ctx, h, {
          rgb,
          rgbLight,
          opacity: opacity * dotsActiveRef.current,
          maxHeightFraction: MAX_HEIGHT_FRACTION,
        }, geometry, performance.now() / 1000)
        rafRef.current = requestAnimationFrame(tick)
      } else {
        // Fully faded out and nothing expected — pause RAF until next event.
        rafRef.current = null
      }
    }

    rafRef.current = requestAnimationFrame(tick)

    // Resume on play (audio events). useTtsExpected also subscribes to
    // audioPlayback for its predicate, but that path goes through
    // resumeRafRef and would also resume the loop. The direct subscribe
    // here keeps the resume path explicit and lets the loop restart even
    // if onTrueEdge is unset (e.g. during a hot-reload window). The
    // rafRef === null guard makes the redundancy harmless.
    const unsubAudio = audioPlayback.subscribe(() => {
      if (rafRef.current === null && !stopped) {
        rafRef.current = requestAnimationFrame(tick)
      }
    })

    // Resume on expectation true-edge (e.g. user submits in live mode).
    resumeRafRef.current = () => {
      if (rafRef.current === null && !stopped) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }

    return () => {
      stopped = true
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      unsubAudio()
      resumeRafRef.current = null
    }
  }, [enabled, style, opacity, barCount, personaColourHex, accessors, paused, ttsExpected, chatview, textColumn, phase])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 1,
      }}
    />
  )
}
