import { useEffect, useState } from 'react'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserPauseStore } from '../stores/visualiserPauseStore'

const FOCUS_OUTLINE = '2px solid rgba(140, 118, 215, 0.6)'

export function VoiceVisualiserHitStrip() {
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)
  const paused = useVisualiserPauseStore((s) => s.paused)
  const togglePause = useVisualiserPauseStore((s) => s.togglePause)

  const [isActive, setIsActive] = useState(audioPlayback.isActive())
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    setIsActive(audioPlayback.isActive())
    return audioPlayback.subscribe(() => setIsActive(audioPlayback.isActive()))
  }, [])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReducedMotion(mq.matches)
    const listener = (e: MediaQueryListEvent) => setReducedMotion(e.matches)
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  if (!enabled) return null
  if (reducedMotion) return null
  if (!isActive && !paused) return null

  return (
    <button
      type="button"
      aria-label={paused ? 'TTS fortsetzen' : 'TTS pausieren'}
      onClick={togglePause}
      style={{
        position: 'fixed',
        left: 0,
        width: '100vw',
        top: '35vh',
        height: '30vh',
        background: 'transparent',
        border: 0,
        padding: 0,
        margin: 0,
        cursor: 'pointer',
        zIndex: 2,
        touchAction: 'manipulation',
        outline: 'none',
      }}
      onFocus={(e) => { e.currentTarget.style.outline = FOCUS_OUTLINE; e.currentTarget.style.outlineOffset = '-4px' }}
      onBlur={(e) => { e.currentTarget.style.outline = 'none' }}
    />
  )
}
