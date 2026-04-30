import { useEffect, useRef } from 'react'

interface Profile {
  count: number
  spawnMs: number
  sizeMin: number
  sizeMax: number
  drift: number
  riseMsMin: number
  riseMsMax: number
}

const PROFILE_FULL: Profile = {
  count: 14,
  spawnMs: 1400,
  sizeMin: 22,
  sizeMax: 38,
  drift: 30,
  riseMsMin: 1900,
  riseMsMax: 2500,
}

const PROFILE_REDUCED: Profile = {
  count: 4,
  spawnMs: 1200,
  sizeMin: 22,
  sizeMax: 30,
  drift: 12,
  riseMsMin: 2300,
  riseMsMax: 2900,
}

const KEYFRAME_NAME = 'screenEffectsRise'

interface Props {
  emojis: string[]
  reduced: boolean
  onDone: () => void
}

/**
 * Renders one burst of rising emojis. Self-contained: appends spans to its
 * own container on mount, removes each particle when its animation ends
 * (or via a safety timeout for jsdom / backgrounded-tab cases), and calls
 * onDone after the last particle finishes. Random parameters per particle
 * are picked here so persisted re-renders (which never invoke this
 * component) cannot differ visually from live ones.
 */
export function RisingEmojisEffect({ emojis, reduced, onDone }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const calledDoneRef = useRef(false)

  // onDone is captured via a ref so identity changes from the parent
  // (e.g. fresh `() => remove(e.id)` closure on every render) do NOT
  // retrigger the spawn effect. Without this, every parent re-render
  // would wipe live particles and re-spawn from scratch.
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const profile = reduced ? PROFILE_REDUCED : PROFILE_FULL
    const safeEmojis = emojis.length > 0 ? emojis : ['✨']
    const stageWidth = window.innerWidth
    const stageHeight = window.innerHeight
    let remaining = profile.count
    const timeouts: number[] = []

    const finish = () => {
      remaining -= 1
      if (remaining <= 0 && !calledDoneRef.current) {
        calledDoneRef.current = true
        onDoneRef.current()
      }
    }

    for (let i = 0; i < profile.count; i += 1) {
      const delay = (i / profile.count) * profile.spawnMs + Math.random() * 120
      const emoji = safeEmojis[Math.floor(Math.random() * safeEmojis.length)]
      const startX = Math.random() * (stageWidth - 40) + 20
      const driftX = (Math.random() - 0.5) * profile.drift * 2
      const size = profile.sizeMin + Math.random() * (profile.sizeMax - profile.sizeMin)
      const rotateStart = (Math.random() - 0.5) * 30
      const rotateEnd = rotateStart + (Math.random() - 0.5) * 90
      const rise = stageHeight + size + 30
      const duration =
        profile.riseMsMin + Math.random() * (profile.riseMsMax - profile.riseMsMin)

      const span = document.createElement('span')
      span.className = 'screen-effect-rising-emoji'
      span.textContent = emoji
      span.style.position = 'absolute'
      span.style.left = `${startX}px`
      span.style.bottom = `${-(size + 20)}px`
      span.style.fontSize = `${size}px`
      span.style.lineHeight = '1'
      span.style.pointerEvents = 'none'
      span.style.userSelect = 'none'
      span.style.willChange = 'transform, opacity'
      span.style.setProperty('--screen-effect-dx', `${driftX}px`)
      span.style.setProperty('--screen-effect-rise', `${rise}px`)
      span.style.setProperty('--screen-effect-rs', `${rotateStart}deg`)
      span.style.setProperty('--screen-effect-re', `${rotateEnd}deg`)
      span.style.animation = `${KEYFRAME_NAME} ${duration}ms cubic-bezier(0.25, 0.6, 0.4, 1) ${delay}ms forwards`

      const onEnd = () => {
        span.removeEventListener('animationend', onEnd)
        if (span.parentNode) span.parentNode.removeChild(span)
        finish()
      }
      span.addEventListener('animationend', onEnd)
      // Safety: even if animationend never fires (jsdom, tab backgrounded),
      // schedule a fallback removal so onDone is still called.
      const safetyTimeout = window.setTimeout(() => {
        if (span.parentNode) {
          span.dispatchEvent(new Event('animationend'))
        }
      }, delay + duration + 500)
      timeouts.push(safetyTimeout)
      container.appendChild(span)
    }

    return () => {
      timeouts.forEach((t) => window.clearTimeout(t))
      while (container.firstChild) {
        container.removeChild(container.firstChild)
      }
    }
  }, [emojis, reduced])

  return (
    <>
      <style>{`
        @keyframes ${KEYFRAME_NAME} {
          0% {
            transform: translate(0, 0) rotate(var(--screen-effect-rs, 0deg)) scale(0.6);
            opacity: 0;
          }
          10% {
            transform: translate(
              calc(var(--screen-effect-dx) * 0.1),
              calc(var(--screen-effect-rise) * -0.1)
            ) rotate(calc(var(--screen-effect-rs) + (var(--screen-effect-re) - var(--screen-effect-rs)) * 0.1)) scale(1);
            opacity: 1;
          }
          85% {
            opacity: 1;
          }
          100% {
            transform: translate(
              var(--screen-effect-dx),
              calc(var(--screen-effect-rise) * -1)
            ) rotate(var(--screen-effect-re, 0deg)) scale(0.9);
            opacity: 0;
          }
        }
      `}</style>
      <div
        ref={containerRef}
        style={{
          position: 'absolute',
          inset: 0,
          overflow: 'hidden',
          pointerEvents: 'none',
        }}
      />
    </>
  )
}
