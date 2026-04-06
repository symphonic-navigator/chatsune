interface ToolCallActivityProps {
  toolName: string
  arguments: Record<string, unknown>
}

const TOOL_LABELS: Record<string, (args: Record<string, unknown>) => string> = {
  web_search: (args) => `Searching the web for "${args.query ?? '...'}"`,
  web_fetch: (args) => {
    const url = String(args.url ?? '')
    const display = url.length > 40 ? url.slice(0, 40) + '...' : url
    return `Fetching ${display}`
  },
  knowledge_search: (args) => `Searching knowledge for "${args.query ?? '...'}"`,
}

export function ToolCallActivity({ toolName, arguments: args }: ToolCallActivityProps) {
  const labelFn = TOOL_LABELS[toolName]
  const label = labelFn ? labelFn(args) : `Running ${toolName}...`
  const isKnowledge = toolName === 'knowledge_search'
  const colour = isKnowledge ? '140,118,215' : '137,180,250'

  return (
    <div
      className="mb-2 flex items-center gap-2 rounded-full px-3 py-1 text-[11px]"
      style={{
        background: `rgba(${colour},0.08)`,
        border: `1px solid rgba(${colour},0.15)`,
        color: `rgba(${colour},0.8)`,
        fontFamily: "'Courier New', monospace",
      }}
    >
      <svg
        className="animate-spin"
        width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      >
        <path d="M12 2a10 10 0 0 1 10 10" />
      </svg>
      {label}
    </div>
  )
}
