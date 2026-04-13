import { useEffect, useRef } from 'react'

const HOLD_THRESHOLD_MS = 300

interface UseCtrlSpaceOptions {
  enabled: boolean
  onHoldStart: () => void
  onHoldEnd: () => void
  onTap: () => void
}

export function useCtrlSpace({ enabled, onHoldStart, onHoldEnd, onTap }: UseCtrlSpaceOptions): void {
  const pressedAt = useRef<number | null>(null)
  const holdTriggered = useRef(false)

  useEffect(() => {
    if (!enabled) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.code !== 'Space' || !e.ctrlKey) return
      if (e.repeat) return
      e.preventDefault()
      pressedAt.current = Date.now()
      holdTriggered.current = false
      setTimeout(() => {
        if (pressedAt.current !== null) {
          holdTriggered.current = true
          onHoldStart()
        }
      }, HOLD_THRESHOLD_MS)
    }

    function onKeyUp(e: KeyboardEvent) {
      if (e.code !== 'Space') return
      if (pressedAt.current === null) return
      e.preventDefault()
      if (holdTriggered.current) onHoldEnd()
      else onTap()
      pressedAt.current = null
      holdTriggered.current = false
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('keyup', onKeyUp)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('keyup', onKeyUp)
    }
  }, [enabled, onHoldStart, onHoldEnd, onTap])
}
