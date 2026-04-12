import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { chatApi, type ToolGroupDto } from '../../core/api/chat'
import { useMcpStore } from '../mcp/mcpStore'
import type { PersonaDto } from '../../core/types/persona'

interface ToolPopoverProps {
  disabledToolGroups: string[]
  personaMcpConfig: PersonaDto['mcp_config']
  onClose: () => void
}

const TIER_COLOURS: Record<string, string> = {
  local: 'rgba(250,179,135,0.8)',   // orange
  remote: 'rgba(166,218,149,0.8)',  // green
  global: 'rgba(203,166,247,0.8)',  // purple
}

function tokenMatch(text: string, tokens: string[]): boolean {
  const lower = text.toLowerCase()
  return tokens.every((t) => lower.includes(t))
}

export function ToolPopover({ disabledToolGroups, personaMcpConfig, onClose }: ToolPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null)
  const [toolGroups, setToolGroups] = useState<ToolGroupDto[]>([])
  const [query, setQuery] = useState('')
  const sessionTools = useMcpStore((s) => s.sessionGateways)

  useEffect(() => {
    chatApi.listToolGroups().then(setToolGroups).catch(console.error)
  }, [])

  // Close on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [onClose])

  const searchTokens = useMemo(
    () => query.trim().toLowerCase().split(/\s+/).filter(Boolean),
    [query],
  )

  const activeBuiltIn = useMemo(
    () =>
      toolGroups.filter(
        (g) =>
          !disabledToolGroups.includes(g.id) &&
          (searchTokens.length === 0 ||
            tokenMatch(g.display_name + ' ' + g.description, searchTokens)),
      ),
    [toolGroups, disabledToolGroups, searchTokens],
  )

  const activeMcp = useMemo(() => {
    const excludedGateways = new Set(personaMcpConfig?.excluded_gateways ?? [])
    const excludedServers = new Set(personaMcpConfig?.excluded_servers ?? [])
    const excludedTools = new Set(personaMcpConfig?.excluded_tools ?? [])

    return sessionTools
      .filter((entry) => !excludedGateways.has(entry.namespace))
      .map((entry) => ({
        ...entry,
        tools: entry.tools.filter((t) => {
          // Persona server exclusion
          if (excludedServers.has(`${entry.namespace}:${t.server_name}`)) return false
          // Persona tool exclusion
          if (excludedTools.has(t.name)) return false
          // Search filter
          if (searchTokens.length > 0 && !tokenMatch((t.name ?? '') + ' ' + (t.description ?? ''), searchTokens)) return false
          return true
        }),
      }))
      .filter((entry) => entry.tools.length > 0)
  }, [sessionTools, searchTokens, personaMcpConfig])

  const totalActive = activeBuiltIn.length + activeMcp.reduce((acc, e) => acc + e.tools.length, 0)

  const handleQueryChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value)
  }, [])

  return (
    <div
      ref={popoverRef}
      role="dialog"
      aria-label="Active tools"
      style={{
        position: 'absolute',
        top: 'calc(100% + 6px)',
        left: 0,
        zIndex: 60,
        width: '340px',
        maxHeight: '360px',
        overflowY: 'auto',
        background: '#1a1726',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '8px',
        boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Search */}
      <div style={{ padding: '8px 10px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <input
          type="text"
          value={query}
          onChange={handleQueryChange}
          placeholder="Search tools…"
          autoFocus
          style={{
            width: '100%',
            background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: '4px',
            padding: '4px 8px',
            fontSize: '12px',
            color: 'rgba(255,255,255,0.7)',
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* Tool list */}
      <div style={{ overflowY: 'auto', flex: 1, padding: '6px 0' }}>
        {/* Built-in tools */}
        {activeBuiltIn.length > 0 && (
          <section>
            <div
              style={{
                padding: '4px 10px 2px',
                fontSize: '10px',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: 'rgba(137,180,250,0.6)',
                fontWeight: 600,
              }}
            >
              Built-in
            </div>
            {activeBuiltIn.map((g) => (
              <div
                key={g.id}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  padding: '3px 10px',
                }}
              >
                <span
                  style={{
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    color: 'rgba(255,255,255,0.75)',
                  }}
                >
                  {g.display_name}
                </span>
                {g.description && (
                  <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>
                    {g.description}
                  </span>
                )}
              </div>
            ))}
          </section>
        )}

        {/* Separator */}
        {activeBuiltIn.length > 0 && activeMcp.length > 0 && (
          <div
            style={{
              margin: '6px 10px',
              borderTop: '1px solid rgba(255,255,255,0.08)',
            }}
          />
        )}

        {/* MCP tools */}
        {activeMcp.map((entry) => (
          <section key={entry.namespace}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '4px 10px 2px',
                fontSize: '10px',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: 'rgba(166,218,149,0.6)',
                fontWeight: 600,
              }}
            >
              {entry.namespace}
              <span
                style={{
                  fontSize: '9px',
                  padding: '1px 4px',
                  borderRadius: '3px',
                  background: 'rgba(255,255,255,0.06)',
                  color: TIER_COLOURS[entry.tier] ?? 'rgba(255,255,255,0.4)',
                  letterSpacing: '0.04em',
                  textTransform: 'none',
                }}
              >
                {entry.tier}
              </span>
            </div>
            {entry.tools.map((t) => (
              <div
                key={t.name}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  padding: '3px 10px',
                }}
              >
                <span
                  style={{
                    fontFamily: 'monospace',
                    fontSize: '11px',
                    color: 'rgba(255,255,255,0.75)',
                  }}
                >
                  {t.name}
                </span>
                {t.description && (
                  <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.35)' }}>
                    {t.description}
                  </span>
                )}
              </div>
            ))}
          </section>
        ))}

        {totalActive === 0 && (
          <div
            style={{
              padding: '16px 10px',
              textAlign: 'center',
              fontSize: '12px',
              color: 'rgba(255,255,255,0.3)',
            }}
          >
            {query ? 'No matching tools' : 'No active tools'}
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          borderTop: '1px solid rgba(255,255,255,0.06)',
          padding: '6px 10px',
          fontSize: '10px',
          color: 'rgba(255,255,255,0.25)',
          textAlign: 'center',
        }}
      >
        {totalActive} tool{totalActive !== 1 ? 's' : ''} active — configure in Settings &gt; MCP
      </div>
    </div>
  )
}
