import { useState } from 'react'
import { useViewport } from '../../core/hooks/useViewport'

type ContextStatus = 'green' | 'yellow' | 'orange' | 'red'

const DOT_COLOURS: Record<ContextStatus, string> = {
  green: 'bg-green-500', yellow: 'bg-yellow-400', orange: 'bg-orange-500', red: 'bg-red-500',
}

const BORDER_COLOURS: Record<ContextStatus, string> = {
  green: 'border-green-500/20', yellow: 'border-yellow-400/20', orange: 'border-orange-500/20', red: 'border-red-500/20',
}

interface ContextStatusPillProps {
  status: ContextStatus
  fillPercentage: number
  usedTokens?: number
  maxTokens?: number
}

export function ContextStatusPill({ status, fillPercentage, usedTokens = 0, maxTokens = 0 }: ContextStatusPillProps) {
  const pct = Math.round(fillPercentage * 100)
  const { isMobile } = useViewport()
  const [open, setOpen] = useState(false)

  const showTokens = usedTokens > 0 && maxTokens > 0
  const interactionProps = isMobile
    ? { onClick: () => setOpen((v) => !v) }
    : { onMouseEnter: () => setOpen(true), onMouseLeave: () => setOpen(false) }

  return (
    <span className="relative inline-flex" {...interactionProps}>
      <span
        className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] ${BORDER_COLOURS[status]} bg-white/3 text-white/40 cursor-default`}
      >
        <span data-testid="context-dot" className={`h-1.5 w-1.5 rounded-full ${DOT_COLOURS[status]}`} />
        <span>{status === 'green' ? 'CTX' : `CTX ${pct}%`}</span>
      </span>
      {open && (
        <div
          role="tooltip"
          className="absolute right-0 top-full mt-2 z-50 w-60 rounded-md border border-white/15 bg-[#0b0a08] lg:bg-[#0b0a08]/95 lg:backdrop-blur-sm shadow-sm lg:shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2 text-[12px] text-white/70 font-mono leading-relaxed"
        >
          <div>Context window: {pct}% used</div>
          {showTokens && (
            <div className="text-white/55">
              {usedTokens.toLocaleString()} of {maxTokens.toLocaleString()} tokens
            </div>
          )}
        </div>
      )}
    </span>
  )
}
