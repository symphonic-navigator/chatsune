import { useCallback, useEffect, useState } from 'react'
import { chatApi, type ToolGroupDto } from '../../core/api/chat'

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
}

export function ToolToggles({
  sessionId, disabledToolGroups, onToggle, disabled, modelSupportsTools,
  modelSupportsReasoning, reasoningOverride, personaReasoningDefault, onReasoningToggle,
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
    </div>
  )
}
