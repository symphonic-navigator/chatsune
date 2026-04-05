import { useCallback, useEffect, useState } from 'react'
import { chatApi, type ToolGroupDto } from '../../core/api/chat'

interface ToolTogglesProps {
  sessionId: string
  disabledToolGroups: string[]
  onToggle: (disabledGroups: string[]) => void
  disabled: boolean
}

export function ToolToggles({ sessionId, disabledToolGroups, onToggle, disabled }: ToolTogglesProps) {
  const [groups, setGroups] = useState<ToolGroupDto[]>([])

  useEffect(() => {
    chatApi.listToolGroups().then(setGroups).catch(() => {})
  }, [])

  const toggleableGroups = groups.filter((g) => g.toggleable)

  const handleToggle = useCallback(
    (groupId: string) => {
      if (disabled) return
      const isDisabled = disabledToolGroups.includes(groupId)
      const updated = isDisabled
        ? disabledToolGroups.filter((id) => id !== groupId)
        : [...disabledToolGroups, groupId]

      onToggle(updated)
      chatApi.updateSessionTools(sessionId, updated).catch(() => {})
    },
    [sessionId, disabledToolGroups, onToggle, disabled],
  )

  if (toggleableGroups.length === 0) return null

  return (
    <div className="flex items-center gap-2">
      {toggleableGroups.map((group) => {
        const isEnabled = !disabledToolGroups.includes(group.id)
        return (
          <button
            key={group.id}
            type="button"
            onClick={() => handleToggle(group.id)}
            disabled={disabled}
            className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              color: isEnabled ? 'rgba(137,180,250,0.9)' : 'rgba(255,255,255,0.35)',
              fontFamily: "'Courier New', monospace",
            }}
            title={group.description}
          >
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: isEnabled ? 'rgba(137,180,250,0.9)' : 'rgba(255,255,255,0.2)',
              }}
            />
            {group.display_name}
          </button>
        )
      })}
    </div>
  )
}
