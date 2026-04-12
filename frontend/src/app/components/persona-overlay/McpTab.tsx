import { useCallback, useEffect, useMemo, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { PersonaMcpConfig } from '../../../features/mcp/types'
import { mcpApi } from '../../../features/mcp/mcpApi'
import { useMcpStore } from '../../../features/mcp/mcpStore'

interface McpTabProps {
  persona: PersonaDto
  chakra: { hex: string; hsl: string }
}

const EMPTY_CONFIG: PersonaMcpConfig = {
  excluded_gateways: [],
  excluded_servers: [],
  excluded_tools: [],
}

const TIER_LABEL: Record<string, string> = { admin: 'global', remote: 'remote', local: 'local' }

export function McpTab({ persona, chakra }: McpTabProps) {
  const sessionGateways = useMcpStore((s) => s.sessionGateways)
  const [config, setConfig] = useState<PersonaMcpConfig>(persona.mcp_config ?? EMPTY_CONFIG)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setConfig(persona.mcp_config ?? EMPTY_CONFIG)
  }, [persona.mcp_config])

  const isGatewayExcluded = useCallback(
    (ns: string) => config.excluded_gateways.includes(ns),
    [config.excluded_gateways],
  )

  const isServerExcluded = useCallback(
    (ns: string, server: string) =>
      config.excluded_gateways.includes(ns) || config.excluded_servers.includes(`${ns}:${server}`),
    [config.excluded_gateways, config.excluded_servers],
  )

  const toggleGateway = useCallback((ns: string) => {
    setConfig((prev) => {
      const excluded = new Set(prev.excluded_gateways)
      if (excluded.has(ns)) excluded.delete(ns)
      else excluded.add(ns)
      return { ...prev, excluded_gateways: [...excluded] }
    })
    setSaved(false)
  }, [])

  const toggleServer = useCallback((ns: string, server: string) => {
    const key = `${ns}:${server}`
    setConfig((prev) => {
      const excluded = new Set(prev.excluded_servers)
      if (excluded.has(key)) excluded.delete(key)
      else excluded.add(key)
      return { ...prev, excluded_servers: [...excluded] }
    })
    setSaved(false)
  }, [])

  const toggleTool = useCallback((toolName: string) => {
    setConfig((prev) => {
      const excluded = new Set(prev.excluded_tools)
      if (excluded.has(toolName)) excluded.delete(toolName)
      else excluded.add(toolName)
      return { ...prev, excluded_tools: [...excluded] }
    })
    setSaved(false)
  }, [])

  /* Group tools by server within each gateway */
  const gatewayServers = useMemo(() => {
    return sessionGateways.map((gw) => {
      const byServer: Record<string, typeof gw.tools> = {}
      for (const tool of gw.tools) {
        const sn = tool.server_name ?? '_unknown'
        if (!byServer[sn]) byServer[sn] = []
        byServer[sn].push(tool)
      }
      return { ...gw, servers: byServer }
    })
  }, [sessionGateways])

  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      await mcpApi.updatePersonaMcp(persona.id, config)
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }, [persona.id, config])

  if (sessionGateways.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
        <p className="text-[13px] text-white/40 leading-relaxed">
          No MCP gateways discovered in this session.
        </p>
        <p className="text-[11px] text-white/25 mt-2">
          Start a chat to discover available tools.
        </p>
      </div>
    )
  }

  return (
    <div className="p-4">
      <p className="text-[11px] text-white/40 mb-4 leading-relaxed">
        Uncheck gateways, servers, or individual tools to exclude them from this persona.
        All tools are enabled by default.
      </p>

      {gatewayServers.map((gw) => {
        const gwExcluded = isGatewayExcluded(gw.namespace)
        return (
          <div key={gw.namespace} className="mb-4">
            {/* Gateway header */}
            <label
              className="flex items-center gap-2.5 px-3 py-2 rounded-md cursor-pointer"
              style={{ background: `${chakra.hex}0a` }}
            >
              <input
                type="checkbox"
                checked={!gwExcluded}
                onChange={() => toggleGateway(gw.namespace)}
                style={{ accentColor: chakra.hex }}
              />
              <span className="text-[13px] font-semibold text-white/80">{gw.namespace}</span>
              <span className="text-[10px] text-white/30 font-mono uppercase tracking-wider">
                {TIER_LABEL[gw.tier] ?? gw.tier}
              </span>
              <span className="text-[10px] text-white/25 ml-auto">
                {gw.tools.length} tools
              </span>
            </label>

            {/* Servers within gateway */}
            {!gwExcluded &&
              Object.entries(gw.servers).map(([serverName, serverTools]) => {
                const serverExcluded = isServerExcluded(gw.namespace, serverName)
                return (
                  <div key={serverName} className="ml-5 mt-1">
                    <label className="flex items-center gap-2 px-2 py-1.5 cursor-pointer rounded hover:bg-white/[0.02]">
                      <input
                        type="checkbox"
                        checked={!serverExcluded}
                        onChange={() => toggleServer(gw.namespace, serverName)}
                        style={{ accentColor: chakra.hex }}
                      />
                      <span className="text-[12px] font-medium text-white/65">{serverName}</span>
                      <span className="text-[10px] text-white/25">{serverTools.length}</span>
                    </label>

                    {/* Tools within server */}
                    {!serverExcluded &&
                      serverTools.map((tool) => {
                        const toolExcluded = config.excluded_tools.includes(tool.name)
                        return (
                          <label
                            key={tool.name}
                            className="flex items-center gap-2 ml-5 px-2 py-1 cursor-pointer rounded hover:bg-white/[0.02]"
                            style={{ opacity: toolExcluded ? 0.4 : 1 }}
                          >
                            <input
                              type="checkbox"
                              checked={!toolExcluded}
                              onChange={() => toggleTool(tool.name)}
                              style={{ accentColor: chakra.hex }}
                            />
                            <span className="text-[11px] font-mono text-white/55">{tool.name}</span>
                            {tool.description && (
                              <span className="text-[10px] text-white/25 truncate max-w-[200px]">
                                {tool.description}
                              </span>
                            )}
                          </label>
                        )
                      })}
                  </div>
                )
              })}
          </div>
        )
      })}

      <div className="flex items-center gap-3 mt-4 pt-3 border-t border-white/6">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-1.5 rounded-md text-[12px] font-medium transition-colors"
          style={{
            background: `${chakra.hex}22`,
            color: `${chakra.hex}cc`,
            border: `1px solid ${chakra.hex}33`,
            cursor: saving ? 'wait' : 'pointer',
          }}
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
        {saved && <span className="text-[11px] text-white/40">Saved</span>}
      </div>
    </div>
  )
}
