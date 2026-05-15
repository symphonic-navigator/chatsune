import { useState } from 'react'
import type { ToolCallRef } from '../../core/api/chat'
import { friendlyLabel, displayName } from './toolLabels'

export type ToolCallPillPhase =
  | {
      kind: 'streaming'
      toolName: string | null
      charCount: number
      argsBuffer: string
      toolCallId: string
    }
  | {
      kind: 'executing'
      toolName: string
      arguments: Record<string, unknown>
      toolCallId: string
    }
  | { kind: 'completed'; ref: ToolCallRef }

interface ToolCallPillProps {
  phase: ToolCallPillPhase
}

function ToolIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M12 2a10 10 0 0 1 10 10" />
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

function colourFor(phase: ToolCallPillPhase): string {
  if (phase.kind === 'completed') {
    return phase.ref.success ? '245,194,131' : '243,139,168'
  }
  if (phase.kind === 'executing') {
    if (phase.toolName === 'knowledge_search') return '140,118,215'
    if (phase.toolName.includes('artefact')) return '201,169,110'
    return '137,180,250'
  }
  return '137,180,250'  // streaming
}

export function ToolCallPill({ phase }: ToolCallPillProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const colour = colourFor(phase)

  const labelNode = (() => {
    if (phase.kind === 'streaming') {
      return (
        <>
          <ToolIcon />
          <span>{phase.toolName ?? 'Tool'}</span>
          <span className="ml-1 opacity-70">{phase.charCount} chars</span>
        </>
      )
    }
    if (phase.kind === 'executing') {
      return (
        <>
          <SpinnerIcon />
          <span>{friendlyLabel(phase.toolName, phase.arguments)}</span>
        </>
      )
    }
    return (
      <>
        <ToolIcon />
        <span>{displayName(phase.ref.tool_name)}</span>
      </>
    )
  })()

  const expandedNode = (() => {
    if (phase.kind === 'streaming') {
      return (
        <>
          <div className="mb-1 text-[10px] font-medium"
            style={{ color: `rgba(${colour},0.9)` }}>
            Streaming arguments…
          </div>
          <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
            style={{ fontFamily: "'Courier New', monospace" }}>
            {phase.argsBuffer || '(empty)'}
          </pre>
        </>
      )
    }
    if (phase.kind === 'executing') {
      return (
        <>
          <div className="mb-1 text-[10px] font-medium"
            style={{ color: `rgba(${colour},0.9)` }}>
            Request
          </div>
          <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
            style={{ fontFamily: "'Courier New', monospace" }}>
            {formatArgs(phase.arguments)}
          </pre>
        </>
      )
    }
    const ref = phase.ref
    const hasResult = ref.result_content != null && ref.result_content !== ''
    return (
      <>
        <div className="mb-1.5 text-[10px] font-medium"
          style={{ color: `rgba(${colour},0.9)` }}>
          {ref.tool_name}
        </div>
        <div className="mb-1 text-[10px] font-medium"
          style={{ color: `rgba(${colour},0.9)` }}>
          Request
        </div>
        <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
          style={{ fontFamily: "'Courier New', monospace" }}>
          {formatArgs(ref.arguments)}
        </pre>
        {hasResult && (
          <>
            <div className="mt-2 mb-1 text-[10px] font-medium"
              style={{ color: `rgba(${colour},0.9)` }}>
              Response
            </div>
            <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
              style={{ fontFamily: "'Courier New', monospace" }}>
              {ref.result_content}
            </pre>
          </>
        )}
      </>
    )
  })()

  return (
    <div className="relative mb-2">
      <button
        type="button"
        onClick={() => setIsExpanded((x) => !x)}
        className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-opacity hover:opacity-90"
        style={{
          background: `rgba(${colour},0.12)`,
          border: `1px solid rgba(${colour},0.25)`,
          color: `rgba(${colour},0.9)`,
          fontFamily: "'Courier New', monospace",
        }}
      >
        {labelNode}
      </button>
      {isExpanded && (
        <div
          className="absolute left-0 top-full z-20 mt-1 min-w-[280px] max-w-[400px] rounded-lg p-3"
          style={{
            background: 'rgba(20, 18, 28, 0.98)',
            border: `1px solid rgba(${colour},0.25)`,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            maxHeight: 320,
            overflowY: 'auto',
          }}
        >
          {expandedNode}
        </div>
      )}
    </div>
  )
}
