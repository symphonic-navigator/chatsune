import { useState } from 'react'
import type { ToolCallRef } from '../../core/api/chat'

interface ToolCallPillsProps {
  toolCalls: ToolCallRef[]
}

function ToolIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  )
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args)
  if (entries.length === 0) return '(no arguments)'
  return entries
    .map(([k, v]) => {
      const val = typeof v === 'string' ? v : JSON.stringify(v)
      const display = val.length > 60 ? val.slice(0, 60) + '...' : val
      return `${k}: ${display}`
    })
    .join('\n')
}

function displayName(toolName: string): string {
  // Strip namespace prefix if present (e.g. "global__quotes_about" -> "quotes_about")
  const parts = toolName.split('__')
  return parts.length > 1 ? parts.slice(1).join('__') : toolName
}

export function ToolCallPills({ toolCalls }: ToolCallPillsProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (toolCalls.length === 0) return null

  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {toolCalls.map((tc, idx) => {
        const colour = tc.success ? '245,194,131' : '243,139,168'
        return (
          <div key={tc.tool_call_id} className="relative">
            <button
              type="button"
              onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-opacity hover:opacity-90"
              style={{
                background: `rgba(${colour},0.12)`,
                border: `1px solid rgba(${colour},0.25)`,
                color: `rgba(${colour},0.9)`,
                fontFamily: "'Courier New', monospace",
              }}
            >
              <ToolIcon />
              {displayName(tc.tool_name)}
            </button>
            {expandedIdx === idx && (
              <div
                className="absolute left-0 top-full z-20 mt-1 min-w-[280px] max-w-[400px] rounded-lg p-3"
                style={{
                  background: 'rgba(20, 18, 28, 0.98)',
                  border: `1px solid rgba(${colour},0.25)`,
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                }}
              >
                <div className="mb-1.5 text-[10px] font-medium" style={{ color: `rgba(${colour},0.9)` }}>
                  {tc.tool_name}
                </div>
                <pre
                  className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
                  style={{ fontFamily: "'Courier New', monospace" }}
                >
                  {formatArgs(tc.arguments)}
                </pre>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
