import { useState } from 'react'
import type { SVGProps } from 'react'
import type { KnowledgeContextItem, PtiOverflow } from '../../core/api/chat'

interface Props {
  items: KnowledgeContextItem[]
  overflow: PtiOverflow | null
}

export function KnowledgePills({ items, overflow }: Props) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const [overflowOpen, setOverflowOpen] = useState(false)

  if (items.length === 0 && !overflow) return null

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {items.map((item, i) => (
          <Pill
            key={i}
            item={item}
            expanded={expandedIdx === i}
            onToggle={() => setExpandedIdx(expandedIdx === i ? null : i)}
          />
        ))}
        {overflow && (
          <button
            type="button"
            onClick={() => setOverflowOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-full bg-white/5 px-3 py-1 text-xs text-white/50"
          >
            +{overflow.dropped_count} limited
          </button>
        )}
      </div>
      {overflow && overflowOpen && (
        <div className="rounded-md border border-white/10 bg-white/5 p-2 text-xs text-white/70">
          <p className="mb-1">Documents not injected (cap reached):</p>
          <ul className="list-disc pl-5">
            {overflow.dropped_titles.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Pill({
  item,
  expanded,
  onToggle,
}: {
  item: KnowledgeContextItem
  expanded: boolean
  onToggle: () => void
}) {
  const Icon = item.source === 'trigger' ? SparklesIcon : BookIcon
  return (
    <div data-source={item.source}>
      <button
        type="button"
        onClick={onToggle}
        className="inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-sm hover:bg-white/10"
      >
        <Icon className="h-3.5 w-3.5" />
        <span className="max-w-[14rem] truncate">{item.document_title}</span>
        {item.score != null && (
          <span className="text-xs text-white/40">
            {item.score.toFixed(2)}
          </span>
        )}
      </button>
      {expanded && (
        <div className="mt-2 rounded-md border border-white/10 bg-white/5 p-2 text-xs text-white/80">
          <p>
            <span className="text-white/40">Library:</span> {item.library_name}
          </p>
          {item.heading_path && item.heading_path.length > 0 && (
            <p>
              <span className="text-white/40">Path:</span>{' '}
              {item.heading_path.join(' › ')}
            </p>
          )}
          {item.source === 'trigger' && item.triggered_by && (
            <p className="text-white/40">
              Triggered by:{' '}
              <span className="font-mono text-white/80">{item.triggered_by}</span>
            </p>
          )}
          {item.preroll_text && (
            <p className="mt-2 text-white/50">{item.preroll_text}</p>
          )}
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-white/70">
            {item.content}
          </pre>
        </div>
      )}
    </div>
  )
}

function BookIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4z" />
      <path d="M4 16a4 4 0 0 1 4-4h12" />
    </svg>
  )
}

function SparklesIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M5 19l3-3M16 8l3-3" />
    </svg>
  )
}
