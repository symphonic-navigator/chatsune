import { useState } from 'react'
import type { WebSearchContextItem } from '../../core/api/chat'

interface WebSearchPillsProps {
  items: WebSearchContextItem[]
}

function SearchIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
}

function FetchIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

export function WebSearchPills({ items }: WebSearchPillsProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (items.length === 0) return null

  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {items.map((item, idx) => {
        const isFetch = item.source_type === 'fetch'
        return (
          <div key={`${item.url}-${idx}`} className="relative">
            <button
              type="button"
              onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-opacity hover:opacity-90"
              style={{
                background: isFetch ? 'rgba(166,218,149,0.12)' : 'rgba(137,180,250,0.12)',
                border: `1px solid ${isFetch ? 'rgba(166,218,149,0.25)' : 'rgba(137,180,250,0.25)'}`,
                color: isFetch ? 'rgba(166,218,149,0.9)' : 'rgba(137,180,250,0.9)',
                fontFamily: "'Courier New', monospace",
              }}
            >
              {isFetch ? <FetchIcon /> : <SearchIcon />}
              {item.title.length > 30 ? item.title.slice(0, 30) + '...' : item.title}
            </button>
            {expandedIdx === idx && (
              <div
                className="absolute left-0 top-full z-20 mt-1 min-w-[280px] max-w-[400px] rounded-lg p-3"
                style={{
                  background: 'rgba(20, 18, 28, 0.98)',
                  border: `1px solid ${isFetch ? 'rgba(166,218,149,0.25)' : 'rgba(137,180,250,0.25)'}`,
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                }}
              >
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mb-1 block text-[10px] hover:underline"
                  style={{
                    color: isFetch ? 'rgba(166,218,149,0.9)' : 'rgba(137,180,250,0.9)',
                    fontFamily: "'Courier New', monospace",
                  }}
                >
                  {item.url.length > 60 ? item.url.slice(0, 60) + '...' : item.url}
                </a>
                <div className="mb-2 text-xs font-medium text-white/80">
                  {item.title}
                </div>
                <div
                  className="text-[11px] leading-relaxed text-white/50"
                  style={{ fontFamily: "'Courier New', monospace" }}
                >
                  {item.snippet}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
