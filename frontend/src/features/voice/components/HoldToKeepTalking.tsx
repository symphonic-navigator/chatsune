import { useCallback, useEffect, useRef } from 'react'

interface HoldToKeepTalkingProps {
  isHolding: boolean
  onHoldStart: () => void
  onHoldEnd: () => void
}

/**
 * Large "Hold to keep talking" overlay. Shown while the user is speaking in
 * conversational mode so they can extend an utterance through a pause
 * without the VAD cutting them off.
 *
 * Hold is "physical" — onMouseDown/onTouchStart engages, release (including
 * mouse leave) disengages. Space bar also works for keyboard users.
 */
export function HoldToKeepTalking({ isHolding, onHoldStart, onHoldEnd }: HoldToKeepTalkingProps) {
  const onHoldStartRef = useRef(onHoldStart)
  const onHoldEndRef = useRef(onHoldEnd)
  useEffect(() => { onHoldStartRef.current = onHoldStart }, [onHoldStart])
  useEffect(() => { onHoldEndRef.current = onHoldEnd }, [onHoldEnd])

  // Keyboard: Space toggles hold while the component is mounted. Browsers
  // fire repeating keydown on Space; we only trigger onHoldStart on the
  // first press.
  const spaceDownRef = useRef(false)
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.code !== 'Space') return
      // Don't hijack space while the user is typing in an input/textarea.
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (spaceDownRef.current) return
      spaceDownRef.current = true
      e.preventDefault()
      onHoldStartRef.current()
    }
    function onKeyUp(e: KeyboardEvent) {
      if (e.code !== 'Space') return
      if (!spaceDownRef.current) return
      spaceDownRef.current = false
      e.preventDefault()
      onHoldEndRef.current()
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('keyup', onKeyUp)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('keyup', onKeyUp)
      if (spaceDownRef.current) {
        spaceDownRef.current = false
        onHoldEndRef.current()
      }
    }
  }, [])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    onHoldStart()
  }, [onHoldStart])

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    e.preventDefault()
    onHoldStart()
  }, [onHoldStart])

  return (
    <div className="pointer-events-none absolute bottom-24 left-1/2 z-40 -translate-x-1/2 select-none">
      <button
        type="button"
        aria-label="Hold to keep talking"
        onMouseDown={handleMouseDown}
        onMouseUp={onHoldEnd}
        onMouseLeave={isHolding ? onHoldEnd : undefined}
        onTouchStart={handleTouchStart}
        onTouchEnd={onHoldEnd}
        onTouchCancel={onHoldEnd}
        className={`pointer-events-auto flex items-center gap-2 rounded-full border px-6 py-4 text-[14px] font-mono uppercase tracking-[0.18em] transition-all shadow-lg ${
          isHolding
            ? 'border-gold/60 bg-gold/20 text-gold shadow-[0_0_24px_rgba(249,226,175,0.3)]'
            : 'border-white/25 bg-[#0f0d16]/90 text-white/80 hover:bg-white/10'
        }`}
      >
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${isHolding ? 'bg-gold animate-pulse' : 'bg-white/60'}`}
        />
        {isHolding ? 'Release to continue' : 'Hold to keep talking'}
      </button>
    </div>
  )
}
