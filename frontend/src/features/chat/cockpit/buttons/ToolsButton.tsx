import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'

export type ToolGroup = {
  id: string
  label: string
  kind: 'builtin' | 'mcp' | 'integration'
}

type Props = {
  sessionId: string
  availableGroups: ToolGroup[]
}

export function ToolsButton({ sessionId, availableGroups }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setTools = useCockpitStore((s) => s.setTools)
  const on = cockpit?.tools ?? false
  const hasAny = availableGroups.length > 0

  if (!hasAny) {
    return (
      <CockpitButton
        icon="🔧"
        state="disabled"
        accent="neutral"
        label="No tools available"
        panel={
          <p className="text-white/70">
            No tools available. Enable web search or connect an integration in persona settings.
          </p>
        }
      />
    )
  }

  return (
    <CockpitButton
      icon="🔧"
      state={on ? 'active' : 'idle'}
      accent="neutral"
      label={on ? `Tools · on · ${availableGroups.length} available` : 'Tools · off'}
      onClick={() => setTools(sessionId, !on)}
      panel={
        <div className="text-white/80">
          <div className="font-semibold mb-2">
            Tools · {on ? 'on' : 'off'} · {availableGroups.length} available
          </div>
          <ul className="text-xs space-y-1">
            {availableGroups.map((g) => (
              <li key={g.id}>
                <span className="text-white/40 uppercase tracking-wider text-[10px] mr-2">
                  {g.kind}
                </span>
                {g.label}
              </li>
            ))}
          </ul>
        </div>
      }
    />
  )
}
