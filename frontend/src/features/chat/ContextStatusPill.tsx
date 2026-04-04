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
}

export function ContextStatusPill({ status, fillPercentage }: ContextStatusPillProps) {
  const showPercentage = status !== 'green'
  const pct = Math.round(fillPercentage * 100)

  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] ${BORDER_COLOURS[status]} bg-white/3 text-white/40`}
      title={`Context window: ${pct}% used`}
    >
      <span data-testid="context-dot" className={`h-1.5 w-1.5 rounded-full ${DOT_COLOURS[status]}`} />
      {showPercentage && <span>{pct}%</span>}
    </span>
  )
}
