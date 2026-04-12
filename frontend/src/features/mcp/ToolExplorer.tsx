import { useCallback, useEffect, useMemo, useState } from 'react'
import type { McpGatewayConfig, McpToolDefinition, McpServerConfig } from './types'
import { mcpToolsList, mcpToolsCall, mcpProxyToolsList, mcpProxyToolsCall } from './mcpClient'

interface ToolExplorerProps {
  gateway: McpGatewayConfig
  tier: 'admin' | 'remote' | 'local'
  onBack: () => void
  onToggleTool: (toolName: string, serverName: string, hidden: boolean) => void
  onRenameTool: (originalName: string, serverName: string, displayName: string | null) => void
  onUpdateServerConfig: (serverName: string, config: Partial<McpServerConfig>) => void
  readOnly?: boolean
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

export function ToolExplorer({
  gateway,
  tier,
  onBack,
  onToggleTool,
  onRenameTool,
  onUpdateServerConfig,
  readOnly = false,
}: ToolExplorerProps) {
  const [tools, setTools] = useState<McpToolDefinition[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedName, setSelectedName] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [response, setResponse] = useState<string | null>(null)
  const [executing, setExecuting] = useState(false)

  const useProxy = tier !== 'local'

  const loadTools = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const { tools: loaded } = useProxy
        ? await mcpProxyToolsList(gateway.id)
        : await mcpToolsList(gateway.url, gateway.api_key)
      setTools(loaded)
      if (loaded.length > 0 && selectedName === null) {
        setSelectedName(loaded[0].name)
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [gateway.id, gateway.url, gateway.api_key, useProxy, selectedName])

  useEffect(() => {
    loadTools()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gateway.url])

  const toolsByServer = useMemo(() => {
    const grouped: Record<string, McpToolDefinition[]> = {}
    for (const tool of tools) {
      const server = tool._gateway_server ?? '_unknown'
      if (!grouped[server]) grouped[server] = []
      grouped[server].push(tool)
    }
    const sorted: Record<string, McpToolDefinition[]> = {}
    for (const key of Object.keys(grouped).sort()) {
      sorted[key] = grouped[key]
    }
    return sorted
  }, [tools])

  const collisions = useMemo(() => {
    const seen = new Map<string, number>()
    for (const tool of tools) {
      seen.set(tool.name, (seen.get(tool.name) ?? 0) + 1)
    }
    return Array.from(seen.entries())
      .filter(([, count]) => count > 1)
      .map(([name]) => name)
  }, [tools])

  const selectedTool = useMemo(
    () => tools.find((t) => t.name === selectedName) ?? null,
    [tools, selectedName],
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
    const result = useProxy
      ? await mcpProxyToolsCall(gateway.id, selectedTool.name, args)
      : await mcpToolsCall(gateway.url, gateway.api_key, selectedTool.name, args)
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
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: '8px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <input
            type="text"
            placeholder="Search tools..."
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

        {/* Tool list grouped by server */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
          {loading && (
            <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: '12px', padding: '12px' }}>
              Loading...
            </div>
          )}
          {loadError && !loading && (
            <div style={{ color: 'rgba(243,139,168,0.8)', fontSize: '12px', padding: '12px' }}>
              {loadError}
            </div>
          )}

          {/* Collision warning */}
          {!loading && !loadError && collisions.length > 0 && (
            <div style={{
              padding: '8px 12px', margin: '4px 8px 8px', borderRadius: 6,
              background: 'rgba(245,169,127,0.12)', border: '1px solid rgba(245,169,127,0.25)',
              fontSize: '11px', color: 'rgba(245,194,131,0.9)',
            }}>
              Name collisions: {collisions.join(', ')} — enable server prefixes or rename to resolve.
            </div>
          )}

          {!loading && !loadError && Object.entries(toolsByServer).map(([serverName, serverTools]) => {
            const serverCfg = gateway.server_configs?.[serverName]
            const isServerHidden = serverCfg?.hidden ?? false

            // Apply search filter
            const filtered = serverTools.filter(t => {
              if (!search.trim()) return true
              const tokens = search.toLowerCase().split(/\s+/).filter(Boolean)
              const hay = `${t.name} ${t.description}`.toLowerCase()
              return tokens.every(tok => hay.includes(tok))
            })
            if (filtered.length === 0 && search) return null

            return (
              <div key={serverName} style={{ marginBottom: 8 }}>
                {/* Server header */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '5px 12px',
                  background: 'rgba(255,255,255,0.03)',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                }}>
                  <span style={{
                    fontWeight: 600, fontSize: 11, flex: 1,
                    color: 'rgba(255,255,255,0.55)',
                    opacity: isServerHidden ? 0.4 : 1,
                    textTransform: 'uppercase', letterSpacing: '0.05em',
                  }}>
                    {serverName}
                  </span>
                  <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>
                    {serverTools.length}
                  </span>
                  {!readOnly && (
                    <button
                      onClick={() => onUpdateServerConfig(serverName, {
                        server_name: serverName,
                        hidden: !isServerHidden,
                        prefix_enabled: serverCfg?.prefix_enabled ?? false,
                        custom_prefix: serverCfg?.custom_prefix ?? null,
                      })}
                      style={{
                        fontSize: 10, color: 'rgba(255,255,255,0.35)', cursor: 'pointer',
                        background: 'none', border: 'none', padding: '0 2px',
                      }}
                    >
                      {isServerHidden ? 'show' : 'hide'}
                    </button>
                  )}
                </div>

                {/* Server prefix controls */}
                {!readOnly && !isServerHidden && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '4px 12px', fontSize: 11,
                    borderBottom: '1px solid rgba(255,255,255,0.03)',
                  }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', color: 'rgba(255,255,255,0.4)' }}>
                      <input
                        type="checkbox"
                        checked={serverCfg?.prefix_enabled ?? false}
                        onChange={e => onUpdateServerConfig(serverName, {
                          server_name: serverName,
                          prefix_enabled: e.target.checked,
                          hidden: serverCfg?.hidden ?? false,
                          custom_prefix: serverCfg?.custom_prefix ?? null,
                        })}
                        style={{ accentColor: 'rgba(137,180,250,0.8)' }}
                      />
                      Prefix
                    </label>
                    {(serverCfg?.prefix_enabled) && (
                      <input
                        type="text"
                        placeholder={normaliseNamespace(serverName)}
                        value={serverCfg?.custom_prefix ?? ''}
                        onChange={e => onUpdateServerConfig(serverName, {
                          server_name: serverName,
                          prefix_enabled: true,
                          hidden: serverCfg?.hidden ?? false,
                          custom_prefix: e.target.value || null,
                        })}
                        style={{
                          background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)',
                          borderRadius: 3, padding: '2px 6px', color: 'rgba(255,255,255,0.7)',
                          fontSize: 11, width: 100, outline: 'none',
                        }}
                      />
                    )}
                  </div>
                )}

                {/* Tools in this server */}
                {!isServerHidden && filtered.map(tool => {
                  const override = gateway.tool_overrides?.find(
                    o => o.original_name === tool.name && o.server_name === serverName
                  )
                  const isHidden = override?.hidden ?? false
                  const selected = tool.name === selectedName
                  return (
                    <button
                      key={`${serverName}:${tool.name}`}
                      onClick={() => handleSelectTool(tool.name)}
                      style={{
                        background: selected ? 'rgba(137,180,250,0.08)' : 'none',
                        border: 'none', borderRadius: 0, cursor: 'pointer',
                        display: 'block', opacity: isHidden ? 0.35 : 1,
                        padding: '6px 12px 6px 20px', textAlign: 'left', width: '100%',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'space-between' }}>
                        <span style={{
                          color: selected ? 'rgba(137,180,250,0.9)' : 'rgba(255,255,255,0.75)',
                          fontFamily: 'monospace', fontSize: 12,
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {override?.display_name ?? tool.name}
                        </span>
                        {isHidden && (
                          <span style={{
                            background: 'rgba(243,139,168,0.2)', borderRadius: 3,
                            color: 'rgba(243,139,168,0.8)', fontSize: 10, flexShrink: 0, padding: '1px 4px',
                          }}>
                            hidden
                          </span>
                        )}
                      </div>
                      <div style={{
                        color: 'rgba(255,255,255,0.3)', fontSize: 11, marginTop: 1,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {tool.description}
                      </div>
                    </button>
                  )
                })}
              </div>
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

                {/* Hide/show toggle */}
                {!readOnly && (
                  <button
                    onClick={() => {
                      const serverName = selectedTool._gateway_server ?? '_unknown'
                      const override = gateway.tool_overrides?.find(
                        o => o.original_name === selectedTool.name && o.server_name === serverName
                      )
                      const currentlyHidden = override?.hidden ?? false
                      onToggleTool(selectedTool.name, serverName, !currentlyHidden)
                    }}
                    style={{
                      background: (() => {
                        const sn = selectedTool._gateway_server ?? '_unknown'
                        const o = gateway.tool_overrides?.find(x => x.original_name === selectedTool.name && x.server_name === sn)
                        return (o?.hidden ?? false) ? 'rgba(243,139,168,0.15)' : 'rgba(166,218,149,0.15)'
                      })(),
                      border: `1px solid ${(() => {
                        const sn = selectedTool._gateway_server ?? '_unknown'
                        const o = gateway.tool_overrides?.find(x => x.original_name === selectedTool.name && x.server_name === sn)
                        return (o?.hidden ?? false) ? 'rgba(243,139,168,0.3)' : 'rgba(166,218,149,0.3)'
                      })()}`,
                      borderRadius: '4px',
                      color: (() => {
                        const sn = selectedTool._gateway_server ?? '_unknown'
                        const o = gateway.tool_overrides?.find(x => x.original_name === selectedTool.name && x.server_name === sn)
                        return (o?.hidden ?? false) ? 'rgba(243,139,168,0.8)' : 'rgba(166,218,149,0.8)'
                      })(),
                      cursor: 'pointer',
                      fontSize: '11px',
                      padding: '3px 8px',
                    }}
                  >
                    {(() => {
                      const serverName = selectedTool._gateway_server ?? '_unknown'
                      const override = gateway.tool_overrides?.find(
                        o => o.original_name === selectedTool.name && o.server_name === serverName
                      )
                      return (override?.hidden ?? false) ? 'Show' : 'Hide'
                    })()}
                  </button>
                )}
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

              {/* Rename field */}
              {!readOnly && (
                <div style={{ marginTop: 8, marginBottom: 12 }}>
                  <label style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>Display name override</label>
                  <input
                    type="text"
                    placeholder={selectedTool.name}
                    value={(() => {
                      const sn = selectedTool._gateway_server ?? '_unknown'
                      return gateway.tool_overrides?.find(o => o.original_name === selectedTool.name && o.server_name === sn)?.display_name ?? ''
                    })()}
                    onChange={e => {
                      const sn = selectedTool._gateway_server ?? '_unknown'
                      onRenameTool(selectedTool.name, sn, e.target.value || null)
                    }}
                    style={{
                      display: 'block', width: '100%', marginTop: 4,
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: 4, padding: '5px 8px', color: 'rgba(255,255,255,0.7)',
                      fontSize: 12, outline: 'none', boxSizing: 'border-box',
                    }}
                  />
                </div>
              )}
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
                          placeholder={`${pName}...`}
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
                {executing ? 'Executing...' : 'Execute'}
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
                <span style={{ color: 'rgba(255,255,255,0.2)' }}>Response will appear here...</span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
