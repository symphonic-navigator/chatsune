import { useState } from 'react'

interface VisionDescriptionBlockProps {
  status: 'pending' | 'success' | 'error'
  modelId: string
  text: string | null
  error: string | null
}

export function VisionDescriptionBlock({
  status,
  modelId,
  text,
  error,
}: VisionDescriptionBlockProps) {
  const [expanded, setExpanded] = useState(false)
  const modelLabel = modelId.split(':').slice(1).join(':') || modelId

  if (status === 'pending') {
    return (
      <div className="mt-1 flex items-center gap-2 rounded-md border border-white/8 bg-white/3 px-2 py-1 text-[11px] text-white/50">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-white/40" />
        Describing image with <span className="font-mono">{modelLabel}</span>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div
        className="mt-1 flex items-center gap-2 rounded-md border px-2 py-1 text-[11px]"
        style={{
          background: 'rgba(243, 139, 168, 0.06)',
          borderColor: 'rgba(243, 139, 168, 0.3)',
          color: 'rgba(243, 139, 168, 0.85)',
        }}
      >
        <span aria-hidden>⚠</span>
        {error ?? 'Vision fallback failed'} — please resend the message
      </div>
    )
  }

  return (
    <div className="mt-1 rounded-md border border-white/8 bg-white/3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-2 py-1 text-[11px] text-white/55 hover:text-white/75"
      >
        <span>
          Vision description{' '}
          <span className="font-mono text-white/35">via {modelLabel}</span>
        </span>
        <span aria-hidden>{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className="border-t border-white/6 px-2 py-1.5 text-[12px] leading-relaxed text-white/70 whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  )
}
