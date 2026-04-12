import { useCallback, useEffect, useMemo, useState } from 'react'
import type { McpGatewayConfig, McpToolDefinition } from './types'
import { mcpToolsList, mcpToolsCall } from './mcpClient'

interface ToolExplorerProps {
  gateway: McpGatewayConfig
  tier: 'admin' | 'remote' | 'local'
  onBack: () => void
  onToggleTool: (toolName: string, disabled: boolean) => void
}

const TIER_COLOUR: Record<string, string> = {
  admin: 'rgba(245,194,131,0.9)',
  remote: 'rgba(137,180,250,0.9)',
  local: 'rgba(166,218,149,0.9)',
}

function normaliseNamespace(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_')
}

export function ToolExplorer({ gateway, tier, onBack, onToggleTool }: ToolExplorerProps) {
  const [tools, setTools] = useState<McpToolDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [response, setResponse] = useState<string | null>(null)
  const [executing, setExecuting] = useState(false)

  const loadTools = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const { tools: loaded } = await mcpToolsList(gateway.url, gateway.api_key)
      setTools(loaded)
      if (loaded.length > 0 && selectedName === null) {
        setSelectedName(loaded[0].name)
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [gateway.url, gateway.api_key, selectedName])

  useEffect(() => {
    loadTools()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gateway.url])

  const filteredTools = useMemo(() => {
    if (!search.trim()) return tools
    const tokens = search.toLowerCase().split(/\s+/).filter(Boolean)
    return tools.filter((t) => {
      const haystack = `${t.name} ${t.description}`.toLowerCase()
      return tokens.every((tok) => haystack.includes(tok))
    })
  }, [tools, search])

  const selectedTool = useMemo(
    () => tools.find((t) => t.name === selectedName) ?? null,
    [tools, selectedName],
  )

  const isDisabled = useCallback(
    (toolName: string) => gateway.disabled_tools.includes(toolName),
    [gateway.disabled_tools],
  )

  const namespace = normaliseNamespace(gateway.name)

  const inputSchema = selectedTool?.inputSchema as
    | { properties?: Record<string, { type?: string; description?: string }>; required?: string[] }
    | undefined

  const params = inputSchema?.properties ?? {}
  const requiredParams = inputSchema?.required ?? []

  function handleParamChange(name: string, value: string) {
    setParamValues((prev) => ({ ...prev, [name]: value }))
  }

  async function handleExecute() {
    if (!selectedTool) return
    setExecuting(true)
    setResponse(null)
    const args: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(paramValues)) {
      if (v !== '') args[k] = v
    }
    const result = await mcpToolsCall(gateway.url, gateway.api_key, selectedTool.name, args)
    if (result.error) {
      setResponse(JSON.stringify({ error: result.error }, null, 2))
    } else {
      try {
        const parsed = JSON.parse(result.stdout)
        setResponse(JSON.stringify(parsed, null, 2))
      } catch {
        setResponse(result.stdout)
      }
    }
    setExecuting(false)
  }

  function handleSelectTool(name: string) {
    setSelectedName(name)
    setParamValues({})
    setResponse(null)
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', height: '100%', minHeight: 0 }}>
      {/* Left panel */}
      <div
        style={{
          borderRight: '1px solid rgba(255,255,255,0.06)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Back + gateway info */}
        <div style={{ padding: '12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <button
            onClick={onBack}
            style={{
              background: 'none',
              border: 'none',
              color: 'rgba(255,255,255,0.5)',
              cursor: 'pointer',
              fontSize: '12px',
              padding: '0 0 8px 0',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            ← Back
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: TIER_COLOUR[tier],
                flexShrink: 0,
              }}
            />
            <span
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: 'rgba(255,255,255,0.85)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {gateway.name}
            </span>
          </div>

          <div
            style={{
              fontSize: '11px',
              color: 'rgba(255,255,255,0.35)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              marginBottom: '8px',
            }}
          >
            {gateway.url}
          </div>

          <button
            onClick={loadTools}
            disabled={loading}
            style={{
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '4px',
              color: 'rgba(255,255,255,0.6)',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '11px',
              padding: '3px 8px',
              width: '100%',
            }}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <input
            type="text"
            placeholder="Search tools…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: '100%',
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '4px',
              color: 'rgba(255,255,255,0.8)',
              fontSize: '12px',
              padding: '5px 8px',
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
        </div>

        {/* Tool list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
          {loading && (
            <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px', padding: '12px' }}>
              Loading…
            </div>
          )}
          {loadError && !loading && (
            <div style={{ color: 'rgba(243,139,168,0.8)', fontSize: '12px', padding: '12px' }}>
              {loadError}
            </div>
          )}
          {!loading &&
            !loadError &&
            filteredTools.map((tool) => {
              const off = isDisabled(tool.name)
              const selected = tool.name === selectedName
              return (
                <button
                  key={tool.name}
                  onClick={() => handleSelectTool(tool.name)}
                  style={{
                    background: selected ? 'rgba(137,180,250,0.08)' : 'none',
                    border: 'none',
                    borderRadius: 0,
                    cursor: 'pointer',
                    display: 'block',
                    opacity: off ? 0.4 : 1,
                    padding: '7px 12px',
                    textAlign: 'left',
                    width: '100%',
                  }}
                >
                  <div
                    style={{
                      alignItems: 'center',
                      display: 'flex',
                      gap: '6px',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span
                      style={{
                        color: selected ? 'rgba(137,180,250,0.9)' : 'rgba(255,255,255,0.75)',
                        fontFamily: 'monospace',
                        fontSize: '12px',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {tool.name}
                    </span>
                    {off && (
                      <span
                        style={{
                          background: 'rgba(243,139,168,0.2)',
                          borderRadius: '3px',
                          color: 'rgba(243,139,168,0.8)',
                          fontSize: '10px',
                          flexShrink: 0,
                          padding: '1px 4px',
                        }}
                      >
                        off
                      </span>
                    )}
                  </div>
                  <div
                    style={{
                      color: 'rgba(255,255,255,0.3)',
                      fontSize: '11px',
                      marginTop: '1px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {tool.description}
                  </div>
                </button>
              )
            })}
        </div>
      </div>

      {/* Right panel */}
      <div style={{ display: 'flex', flexDirection: 'column', overflow: 'auto', padding: '20px 24px' }}>
        {!selectedTool && !loading && (
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: '13px' }}>
            Select a tool from the list.
          </div>
        )}

        {selectedTool && (
          <>
            {/* Tool header */}
            <div style={{ marginBottom: '16px' }}>
              <div style={{ alignItems: 'center', display: 'flex', gap: '12px', marginBottom: '2px' }}>
                <span
                  style={{
                    color: 'rgba(255,255,255,0.9)',
                    fontFamily: 'monospace',
                    fontSize: '18px',
                    fontWeight: 600,
                  }}
                >
                  {selectedTool.name}
                </span>

                {/* Enable/disable toggle */}
                <button
                  onClick={() => onToggleTool(selectedTool.name, !isDisabled(selectedTool.name))}
                  style={{
                    background: isDisabled(selectedTool.name)
                      ? 'rgba(243,139,168,0.15)'
                      : 'rgba(166,218,149,0.15)',
                    border: `1px solid ${isDisabled(selectedTool.name) ? 'rgba(243,139,168,0.3)' : 'rgba(166,218,149,0.3)'}`,
                    borderRadius: '4px',
                    color: isDisabled(selectedTool.name)
                      ? 'rgba(243,139,168,0.8)'
                      : 'rgba(166,218,149,0.8)',
                    cursor: 'pointer',
                    fontSize: '11px',
                    padding: '3px 8px',
                  }}
                >
                  {isDisabled(selectedTool.name) ? 'Enable' : 'Disable'}
                </button>
              </div>

              <div
                style={{
                  color: 'rgba(255,255,255,0.35)',
                  fontFamily: 'monospace',
                  fontSize: '12px',
                  marginBottom: '8px',
                }}
              >
                {namespace}__{selectedTool.name}
              </div>

              <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: '13px', lineHeight: 1.5 }}>
                {selectedTool.description}
              </div>
            </div>

            {/* Parameters */}
            {Object.keys(params).length > 0 && (
              <div style={{ marginBottom: '16px' }}>
                <div
                  style={{
                    color: 'rgba(255,255,255,0.5)',
                    fontSize: '11px',
                    fontWeight: 600,
                    letterSpacing: '0.08em',
                    marginBottom: '10px',
                    textTransform: 'uppercase',
                  }}
                >
                  Parameters
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {Object.entries(params).map(([pName, pSchema]) => {
                    const required = requiredParams.includes(pName)
                    return (
                      <div key={pName}>
                        <div
                          style={{
                            alignItems: 'center',
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: '6px',
                            marginBottom: '4px',
                          }}
                        >
                          <span
                            style={{
                              color: 'rgba(137,180,250,0.9)',
                              fontFamily: 'monospace',
                              fontSize: '13px',
                            }}
                          >
                            {pName}
                          </span>

                          {pSchema.type && (
                            <span
                              style={{
                                background: 'rgba(255,255,255,0.07)',
                                borderRadius: '3px',
                                color: 'rgba(255,255,255,0.45)',
                                fontSize: '10px',
                                padding: '1px 5px',
                              }}
                            >
                              {pSchema.type}
                            </span>
                          )}

                          {required && (
                            <span
                              style={{
                                background: 'rgba(245,194,131,0.2)',
                                borderRadius: '3px',
                                color: 'rgba(245,194,131,0.9)',
                                fontSize: '10px',
                                padding: '1px 5px',
                              }}
                            >
                              required
                            </span>
                          )}
                        </div>

                        {pSchema.description && (
                          <div
                            style={{
                              color: 'rgba(255,255,255,0.4)',
                              fontSize: '12px',
                              marginBottom: '5px',
                            }}
                          >
                            {pSchema.description}
                          </div>
                        )}

                        <input
                          type="text"
                          placeholder={`${pName}…`}
                          value={paramValues[pName] ?? ''}
                          onChange={(e) => handleParamChange(pName, e.target.value)}
                          style={{
                            background: 'rgba(255,255,255,0.04)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: '4px',
                            color: 'rgba(255,255,255,0.8)',
                            fontSize: '12px',
                            outline: 'none',
                            padding: '6px 10px',
                            width: '100%',
                            boxSizing: 'border-box',
                          }}
                        />
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Execute */}
            <div style={{ marginBottom: '16px' }}>
              <button
                onClick={handleExecute}
                disabled={executing}
                style={{
                  background: executing ? 'rgba(166,218,149,0.08)' : 'rgba(166,218,149,0.15)',
                  border: '1px solid rgba(166,218,149,0.3)',
                  borderRadius: '5px',
                  color: 'rgba(166,218,149,0.9)',
                  cursor: executing ? 'not-allowed' : 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                  padding: '7px 18px',
                }}
              >
                {executing ? 'Executing…' : 'Execute'}
              </button>
            </div>

            {/* Response */}
            <div
              style={{
                background: 'rgba(0,0,0,0.3)',
                borderRadius: '6px',
                border: '1px solid rgba(255,255,255,0.06)',
                color: 'rgba(166,218,149,0.7)',
                fontFamily: 'monospace',
                fontSize: '12px',
                lineHeight: 1.6,
                minHeight: '80px',
                padding: '12px',
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {response ?? (
                <span style={{ color: 'rgba(255,255,255,0.2)' }}>Response will appear here…</span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
