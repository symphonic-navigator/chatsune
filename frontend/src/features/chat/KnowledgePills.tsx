import { useState } from 'react'
import type { RetrievedChunkDto } from '../../core/types/knowledge'

interface KnowledgePillsProps {
  items: RetrievedChunkDto[]
}

function BookIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  )
}

export function KnowledgePills({ items }: KnowledgePillsProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (items.length === 0) return null

  return (
    <div className="mb-2">
      <div
        className="mb-1 text-[10px]"
        style={{ fontFamily: "'Courier New', monospace", color: 'rgba(255,255,255,0.3)' }}
      >
        RETRIEVED KNOWLEDGE
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item, idx) => {
          const title = item.document_title.length > 30
            ? item.document_title.slice(0, 30) + '...'
            : item.document_title
          const score = (item.score * 100).toFixed(0)

          return (
            <div key={idx} className="relative">
              <button
                type="button"
                onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
                className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-opacity hover:opacity-90"
                style={{
                  background: 'rgba(140,118,215,0.08)',
                  border: '1px solid rgba(140,118,215,0.15)',
                  color: 'rgba(140,118,215,0.9)',
                  fontFamily: "'Courier New', monospace",
                }}
              >
                <BookIcon />
                {title}
                <span style={{ color: 'rgba(140,118,215,0.5)', fontSize: '9px' }}>
                  {score}%
                </span>
              </button>
              {expandedIdx === idx && (
                <div
                  className="absolute left-0 top-full z-20 mt-1 min-w-[280px] max-w-[400px] rounded-lg p-3"
                  style={{
                    background: 'rgba(20,18,28,0.98)',
                    border: '1px solid rgba(140,118,215,0.15)',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  }}
                >
                  <div
                    className="mb-1 text-[10px]"
                    style={{ fontFamily: "'Courier New', monospace" }}
                  >
                    <span style={{ color: 'rgba(140,118,215,0.5)' }}>{item.library_name}</span>
                    <span style={{ color: 'rgba(140,118,215,0.3)' }}> &rsaquo; </span>
                    <span style={{ color: 'rgba(140,118,215,0.9)' }}>{item.document_title}</span>
                  </div>
                  {item.heading_path.length > 0 && (
                    <div
                      className="mb-2 text-[10px] text-white/30"
                      style={{ fontFamily: "'Courier New', monospace" }}
                    >
                      {item.heading_path.join(' / ')}
                    </div>
                  )}
                  {item.preroll_text && (
                    <div
                      className="mb-2 text-[10px] text-white/30"
                      style={{ fontFamily: "'Courier New', monospace" }}
                    >
                      {item.preroll_text}
                    </div>
                  )}
                  <div
                    className="mb-2 text-[11px] leading-relaxed text-white/70"
                    style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}
                  >
                    {item.content.length > 500
                      ? item.content.slice(0, 500) + '…'
                      : item.content}
                  </div>
                  <div
                    className="text-[10px]"
                    style={{
                      color: 'rgba(140,118,215,0.5)',
                      fontFamily: "'Courier New', monospace",
                    }}
                  >
                    score: {item.score.toFixed(4)}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
