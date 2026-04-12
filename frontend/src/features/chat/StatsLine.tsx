import { useState } from 'react'

interface StatsLineProps {
  timeToFirstTokenMs: number | null | undefined
  tokensPerSecond: number | null | undefined
  generationDurationMs: number | null | undefined
  outputTokens: number | null | undefined
  providerName: string | null | undefined
  modelName: string | null | undefined
}

function formatTtft(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function StatsLine({
  timeToFirstTokenMs,
  tokensPerSecond,
  // generationDurationMs reserved for future use
  outputTokens,
  providerName,
  modelName,
}: StatsLineProps) {
  const [expanded, setExpanded] = useState(false)

  const hasAny = timeToFirstTokenMs != null || tokensPerSecond != null || outputTokens != null
  if (!hasAny) return null

  const parts: string[] = []
  if (timeToFirstTokenMs != null) parts.push(`TTFT: ${formatTtft(timeToFirstTokenMs)}`)
  if (tokensPerSecond != null) parts.push(`${tokensPerSecond} tok/s`)
  if (outputTokens != null) parts.push(`${outputTokens} tokens`)

  const modelPart = providerName && modelName
    ? `${providerName} / ${modelName}`
    : providerName || modelName || null

  if (modelPart) parts.push(modelPart)

  return (
    <div className="mt-1">
      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex items-center gap-1 text-[11px] text-white/20 transition-colors hover:text-white/40"
          title="Show inference stats"
        >
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
            <path d="M7 6V10M7 4.5V4.51" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
          <span>stats</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="text-[11px] text-white/30 transition-colors hover:text-white/40"
        >
          {parts.join(' \u00B7 ')}
        </button>
      )}
    </div>
  )
}
