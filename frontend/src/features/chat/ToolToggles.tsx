import { useCallback, useEffect, useState } from 'react'
import { chatApi, type ToolGroupDto } from '../../core/api/chat'
import { useMcpStore } from '../mcp/mcpStore'
import { useIntegrationsStore } from '../integrations/store'

interface ToolTogglesProps {
  sessionId: string
  disabledToolGroups: string[]
  onToggle: (disabledGroups: string[]) => void
  disabled: boolean
  modelSupportsTools: boolean
  modelSupportsReasoning: boolean
  reasoningOverride: boolean | null
  personaReasoningDefault: boolean
  onReasoningToggle: (override: boolean | null) => void
  filteredMcpToolCount?: number
}

export function ToolToggles({
  sessionId, disabledToolGroups, onToggle, disabled, modelSupportsTools,
  modelSupportsReasoning, reasoningOverride, personaReasoningDefault, onReasoningToggle,
  filteredMcpToolCount,
}: ToolTogglesProps) {
  const [groups, setGroups] = useState<ToolGroupDto[]>([])

  useEffect(() => {
    chatApi.listToolGroups().then(setGroups).catch(() => {})
  }, [])

  const toggleableGroups = groups.filter((g) => g.toggleable)

  const handleToggle = useCallback(
    (groupId: string) => {
      if (disabled || !modelSupportsTools) return
      const isDisabled = disabledToolGroups.includes(groupId)
      const updated = isDisabled
        ? disabledToolGroups.filter((id) => id !== groupId)
        : [...disabledToolGroups, groupId]

      onToggle(updated)
      chatApi.updateSessionTools(sessionId, updated).catch(() => {})
    },
    [sessionId, disabledToolGroups, onToggle, disabled, modelSupportsTools],
  )

  const { localGateways, sessionGateways } = useMcpStore()
  // Use filtered count from parent if available, otherwise count all
  const mcpToolCount = filteredMcpToolCount ?? sessionGateways.reduce((sum, g) => sum + g.tools.length, 0)
  // MCP toggle is visible if there are any configured gateways (local or remote discovered)
  const hasMcpGateways = localGateways.some((gw) => gw.enabled) || sessionGateways.length > 0
  const mcpEnabled = modelSupportsTools && !disabledToolGroups.includes('mcp')

  const reasoningEnabled = reasoningOverride !== null ? reasoningOverride : personaReasoningDefault

  const handleReasoningToggle = useCallback(() => {
    if (disabled || !modelSupportsReasoning) return
    const newValue = !reasoningEnabled
    // If toggling back to persona default, clear the override
    const override = newValue === personaReasoningDefault ? null : newValue
    onReasoningToggle(override)
    chatApi.updateSessionReasoning(sessionId, override).catch(() => {})
  }, [sessionId, disabled, modelSupportsReasoning, reasoningEnabled, personaReasoningDefault, onReasoningToggle])

  if (toggleableGroups.length === 0 && !modelSupportsReasoning) return null

  return (
    <div className="flex items-center gap-3">
      {modelSupportsReasoning && (
        <button
          type="button"
          onClick={handleReasoningToggle}
          disabled={disabled}
          className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          style={{
            color: reasoningEnabled ? 'rgba(249,226,175,0.9)' : 'rgba(255,255,255,0.35)',
            fontFamily: "'Courier New', monospace",
          }}
          title={reasoningEnabled ? 'Disable reasoning for this session' : 'Enable reasoning for this session'}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{
              backgroundColor: reasoningEnabled ? 'rgba(249,226,175,0.9)' : 'rgba(255,255,255,0.2)',
            }}
          />
          Thinking
        </button>
      )}
      {toggleableGroups.map((group) => {
        const isEnabled = modelSupportsTools && !disabledToolGroups.includes(group.id)
        const isUnavailable = !modelSupportsTools
        return (
          <button
            key={group.id}
            type="button"
            onClick={() => handleToggle(group.id)}
            disabled={disabled || isUnavailable}
            className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              color: isEnabled ? 'rgba(137,180,250,0.9)' : 'rgba(255,255,255,0.2)',
              fontFamily: "'Courier New', monospace",
            }}
            title={isUnavailable ? 'Model does not support tool calls' : group.description}
          >
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: isEnabled ? 'rgba(137,180,250,0.9)' : 'rgba(255,255,255,0.15)',
              }}
            />
            {group.display_name}
          </button>
        )
      })}
      {hasMcpGateways && (
        <>
          <div
            className="mx-0.5 h-3.5 w-px"
            style={{ backgroundColor: 'rgba(255,255,255,0.08)' }}
          />
          <button
            type="button"
            onClick={() => handleToggle('mcp')}
            disabled={disabled || !modelSupportsTools}
            className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              color: mcpEnabled ? 'rgba(166,218,149,0.9)' : 'rgba(255,255,255,0.2)',
              fontFamily: "'Courier New', monospace",
            }}
            title="MCP tools from connected gateways"
          >
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: mcpEnabled
                  ? 'rgba(166,218,149,0.9)'
                  : 'rgba(255,255,255,0.15)',
              }}
            />
            MCP
            {mcpEnabled && mcpToolCount > 0 && (
              <span
                style={{
                  color: 'rgba(166,218,149,0.5)',
                  fontSize: '9px',
                  marginLeft: '2px',
                }}
              >
                {mcpToolCount}
              </span>
            )}
          </button>
        </>
      )}
      <IntegrationToolIndicator modelSupportsTools={modelSupportsTools} />
    </div>
  )
}

/** Read-only indicator for active integration tools. */
function IntegrationToolIndicator({ modelSupportsTools }: { modelSupportsTools: boolean }) {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)
  const loaded = useIntegrationsStore((s) => s.loaded)

  if (!loaded) return null

  const enabledDefs = definitions.filter((d) => configs.get(d.id)?.enabled && d.has_tools)
  if (enabledDefs.length === 0) return null

  const toolCount = enabledDefs.reduce((sum, d) => {
    return sum + (d.has_tools ? 2 : 0) // get_toys + control per integration
  }, 0)

  const active = modelSupportsTools

  return (
    <>
      <div
        className="mx-0.5 h-3.5 w-px"
        style={{ backgroundColor: 'rgba(255,255,255,0.08)' }}
      />
      <span
        className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide"
        style={{
          color: active ? 'rgba(196,167,231,0.9)' : 'rgba(255,255,255,0.2)',
          fontFamily: "'Courier New', monospace",
        }}
        title={`Integration tools from: ${enabledDefs.map((d) => d.display_name).join(', ')}`}
      >
        <span
          className="inline-block h-1.5 w-1.5 rounded-full"
          style={{
            backgroundColor: active ? 'rgba(196,167,231,0.9)' : 'rgba(255,255,255,0.15)',
          }}
        />
        Integrations
        {active && toolCount > 0 && (
          <span
            style={{
              color: 'rgba(196,167,231,0.5)',
              fontSize: '9px',
              marginLeft: '2px',
            }}
          >
            {toolCount}
          </span>
        )}
      </span>
    </>
  )
}
