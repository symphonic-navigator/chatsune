import { useCallback, useEffect, useState } from 'react'
import { mcpApi } from '../../../features/mcp/mcpApi'
import { GatewayEditDialog } from '../../../features/mcp/GatewayEditDialog'
import { ToolExplorer } from '../../../features/mcp/ToolExplorer'
import type { McpGatewayConfig, McpServerConfig } from '../../../features/mcp/types'

type View =
  | { kind: 'list' }
  | { kind: 'edit'; gateway?: McpGatewayConfig }
  | { kind: 'explore'; gateway: McpGatewayConfig }

export function AdminMcpTab() {
  const [gateways, setGateways] = useState<McpGatewayConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>({ kind: 'list' })

  const fetchGateways = useCallback(async () => {
    setError(null)
    try {
      const data = await mcpApi.listAdminGateways()
      setGateways(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load admin gateways')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchGateways()
  }, [fetchGateways])

  // ── curation handlers ────────────────────────────────────────────────
  const persistGatewayUpdate = useCallback(
    async (gatewayId: string, patch: Parameters<typeof mcpApi.updateAdminGateway>[1]) => {
      try {
        await mcpApi.updateAdminGateway(gatewayId, patch)
        await fetchGateways()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to update gateway')
        await fetchGateways()
      }
    },
    [fetchGateways],
  )

  function handleToggleTool(gateway: McpGatewayConfig, toolName: string, serverName: string, hidden: boolean) {
    const overrides = [...(gateway.tool_overrides ?? [])]
    const idx = overrides.findIndex(o => o.original_name === toolName && o.server_name === serverName)
    if (idx >= 0) {
      overrides[idx] = { ...overrides[idx], hidden }
    } else {
      overrides.push({ original_name: toolName, server_name: serverName, display_name: null, hidden })
    }
    void persistGatewayUpdate(gateway.id, { tool_overrides: overrides })
    setGateways(prev => prev.map(g => g.id === gateway.id ? { ...g, tool_overrides: overrides } : g))
  }

  function handleRenameTool(gateway: McpGatewayConfig, originalName: string, serverName: string, displayName: string | null) {
    const overrides = [...(gateway.tool_overrides ?? [])]
    const idx = overrides.findIndex(o => o.original_name === originalName && o.server_name === serverName)
    if (idx >= 0) {
      overrides[idx] = { ...overrides[idx], display_name: displayName }
    } else {
      overrides.push({ original_name: originalName, server_name: serverName, display_name: displayName, hidden: false })
    }
    void persistGatewayUpdate(gateway.id, { tool_overrides: overrides })
    setGateways(prev => prev.map(g => g.id === gateway.id ? { ...g, tool_overrides: overrides } : g))
  }

  function handleUpdateServerConfig(gateway: McpGatewayConfig, serverName: string, config: Partial<McpServerConfig>) {
    const configs = { ...(gateway.server_configs ?? {}) }
    const existing = configs[serverName] ?? { server_name: serverName, prefix_enabled: false, custom_prefix: null, hidden: false }
    configs[serverName] = { ...existing, ...config }
    void persistGatewayUpdate(gateway.id, { server_configs: configs })
    setGateways(prev => prev.map(g => g.id === gateway.id ? { ...g, server_configs: configs } : g))
  }

  // ── Explore view ────────────────────────────────────────────────────
  if (view.kind === 'explore') {
    // Always read the freshest gateway from state (mutations update gateways[])
    const gw = gateways.find(g => g.id === view.gateway.id) ?? view.gateway
    return (
      <div className="flex flex-1 flex-col overflow-hidden">
        <ToolExplorer
          gateway={gw}
          tier="admin"
          onBack={() => setView({ kind: 'list' })}
          onToggleTool={(toolName, serverName, hidden) => handleToggleTool(gw, toolName, serverName, hidden)}
          onRenameTool={(orig, server, display) => handleRenameTool(gw, orig, server, display)}
          onUpdateServerConfig={(server, cfg) => handleUpdateServerConfig(gw, server, cfg)}
        />
      </div>
    )
  }

  // ── Edit / Create view ──────────────────────────────────────────────
  if (view.kind === 'edit') {
    const isEdit = !!view.gateway
    return (
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <button
          type="button"
          onClick={() => setView({ kind: 'list' })}
          className="self-start text-[11px] text-white/40 hover:text-white/70 transition-colors"
        >
          &larr; Back to gateways
        </button>
        <GatewayEditDialog
          mode={isEdit ? 'edit' : 'create'}
          gateway={view.gateway}
          tier="remote"
          onSave={async (gw) => {
            if (isEdit) {
              await mcpApi.updateAdminGateway(gw.id, gw)
            } else {
              await mcpApi.createAdminGateway({ name: gw.name, url: gw.url, api_key: gw.api_key, enabled: gw.enabled })
            }
            await fetchGateways()
            setView({ kind: 'list' })
          }}
          onDelete={
            isEdit
              ? async () => {
                  await mcpApi.deleteAdminGateway(view.gateway!.id)
                  await fetchGateways()
                  setView({ kind: 'list' })
                }
              : undefined
          }
          onCancel={() => setView({ kind: 'list' })}
        />
      </div>
    )
  }

  // ── List view ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Loading gateways...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div>
        <h3 className="text-[13px] font-medium text-white/80">Global MCP Gateways</h3>
        <p className="mt-1 text-[11px] text-white/60 leading-relaxed">
          Configure MCP gateways available to all users. API keys are managed here
          and not visible to users. The URL must be reachable from the backend
          (e.g. use Docker service names like <code className="text-white/40">http://mcp-gateway:9100</code> for
          containerised deployments).
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[11px] text-red-400">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-white/40">
          {gateways.length} gateway{gateways.length !== 1 ? 's' : ''} configured
        </span>
        <button
          type="button"
          onClick={() => setView({ kind: 'edit' })}
          className="text-[11px] px-3 py-1 rounded border transition-colors"
          style={{
            borderColor: 'rgba(140,118,215,0.3)',
            backgroundColor: 'rgba(140,118,215,0.08)',
            color: 'rgba(140,118,215,0.9)',
          }}
        >
          + Add Gateway
        </button>
      </div>

      {gateways.length === 0 && !error && (
        <div className="rounded-lg border border-white/6 bg-white/2 px-4 py-8 text-center text-[12px] text-white/30">
          No global MCP gateways configured yet.
        </div>
      )}

      <div className="flex flex-col gap-2">
        {gateways.map((gw) => (
          <div
            key={gw.id}
            className="rounded-lg border px-3 py-2.5 transition-colors"
            style={{
              borderColor: gw.enabled ? 'rgba(140,118,215,0.15)' : 'rgba(255,255,255,0.05)',
              backgroundColor: gw.enabled ? 'rgba(140,118,215,0.05)' : 'rgba(255,255,255,0.02)',
              opacity: gw.enabled ? 1 : 0.5,
            }}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className="h-2 w-2 flex-shrink-0 rounded-full"
                  style={{
                    backgroundColor: gw.enabled
                      ? 'rgba(140,118,215,0.8)'
                      : 'rgba(255,255,255,0.2)',
                  }}
                />
                <div className="min-w-0">
                  <div className="text-[13px] font-medium text-white/85 truncate">{gw.name}</div>
                  <div className="text-[11px] text-white/40 font-mono truncate">{gw.url}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                {gw.enabled ? (
                  <span
                    className="text-[10px] rounded-full px-2 py-0.5"
                    style={{
                      color: 'rgba(140,118,215,0.7)',
                      backgroundColor: 'rgba(140,118,215,0.1)',
                    }}
                  >
                    enabled
                  </span>
                ) : (
                  <span className="text-[10px] rounded-full px-2 py-0.5 text-white/30 bg-white/5">
                    disabled
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setView({ kind: 'explore', gateway: gw })}
                  className="text-[11px] px-2 py-0.5 rounded border transition-colors"
                  style={{
                    borderColor: 'rgba(137,180,250,0.2)',
                    color: 'rgba(137,180,250,0.7)',
                    backgroundColor: 'transparent',
                  }}
                >
                  Explore
                </button>
                <button
                  type="button"
                  onClick={() => setView({ kind: 'edit', gateway: gw })}
                  className="text-[11px] px-2 py-0.5 rounded border border-white/10 text-white/40 hover:text-white/70 transition-colors"
                >
                  Edit
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
