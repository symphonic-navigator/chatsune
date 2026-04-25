import { useState, useRef, useEffect } from 'react'
import type { ReactNode } from 'react'
import { useViewport } from '@/core/hooks/useViewport'

export type CockpitButtonState =
  | 'active'        // feature is on / running
  | 'idle'          // feature is available and off
  | 'disabled'      // feature is not available in the current context
  | 'playback'      // transient playback / stop state

type Props = {
  icon: ReactNode
  state: CockpitButtonState
  accent?: 'gold' | 'blue' | 'purple' | 'green' | 'neutral'
  label: string
  panel?: ReactNode
  onClick?: () => void
  ariaLabel?: string
}

const ACCENT_CLASSES: Record<NonNullable<Props['accent']>, string> = {
  gold:   'text-[#d4af37] border-[#d4af37]/35 bg-[#d4af37]/15',
  blue:   'text-[#60a5fa] border-[#3b82f6]/35 bg-[#3b82f6]/15',
  purple: 'text-[#c084fc] border-[#a855f7]/35 bg-[#a855f7]/15',
  green:  'text-[#4ade80] border-[#22c55e]/35 bg-[#22c55e]/15',
  neutral:'text-white/85 border-white/20 bg-white/10',
}

export function CockpitButton({
  icon, state, accent = 'neutral', label, panel, onClick, ariaLabel,
}: Props) {
  const { isMobile } = useViewport()
  const [panelOpen, setPanelOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const closeTimer = useRef<number | null>(null)

  // Panels are a hover affordance — meaningless on touch, where they fire
  // as phantom mouseenter on tap. Mobile discovery routes through the (i)
  // info modal instead, so we suppress panel rendering entirely here.
  const panelEnabled = Boolean(panel) && !isMobile

  useEffect(() => () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current)
  }, [])

  const open = () => {
    if (!panelEnabled) return
    if (closeTimer.current) window.clearTimeout(closeTimer.current)
    setPanelOpen(true)
  }
  const scheduleClose = () => {
    if (!panelEnabled) return
    closeTimer.current = window.setTimeout(() => setPanelOpen(false), 120)
  }

  const base = 'inline-flex items-center justify-center h-8 w-8 lg:h-9 lg:w-9 rounded-md border transition'
  const disabled = state === 'disabled'
  // A disabled button becomes an actionable "needs setup" button when the
  // caller still provides an onClick — it keeps the muted visual but accepts
  // clicks (e.g. open the persona voice settings).
  const actionable = !disabled || Boolean(onClick)
  const classes = disabled
    ? `${base} border-dashed border-white/15 bg-white/5 text-white/30 ${
        onClick ? 'cursor-pointer hover:text-white/50' : 'cursor-not-allowed'
      }`
    : state === 'active' || state === 'playback'
      ? `${base} ${ACCENT_CLASSES[accent]}`
      : `${base} border-transparent bg-white/5 text-white/70 hover:bg-white/10`

  return (
    <div
      ref={containerRef}
      className="relative"
      onMouseEnter={open}
      onMouseLeave={scheduleClose}
    >
      <button
        type="button"
        disabled={!actionable}
        aria-label={ariaLabel ?? label}
        title={label}
        className={classes}
        onClick={onClick}
      >
        {icon}
      </button>
      {panelEnabled && panelOpen && (
        <div
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-40 min-w-[260px] max-w-[360px] rounded-lg border border-white/10 bg-[#1a1625] p-3 text-sm shadow-xl"
          onMouseEnter={open}
          onMouseLeave={scheduleClose}
          role="tooltip"
        >
          {panel}
        </div>
      )}
    </div>
  )
}
