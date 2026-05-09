import type { ToolCapability } from '@/core/types/llm'
import { CockpitButton } from '../CockpitButton'

/**
 * Tool group descriptor for the panel listing. Surfaced to the user so
 * they can see which built-in / MCP / integration toolsets the assistant
 * is allowed to call when Tools is on. Kept as a pure DTO for the panel —
 * the buttons themselves only need ``ToolCapability``.
 */
export type ToolGroup = {
  id: string
  label: string
  kind: 'builtin' | 'mcp' | 'integration'
}

type Props = {
  tools: ToolCapability
  enabled: boolean
  /**
   * Optional list of available tool groups, surfaced inside the hover
   * panel. Empty list = "no tools wired up yet" — the button still works
   * but the panel hint reflects that.
   */
  availableGroups?: ToolGroup[]
  onChange: (enabled: boolean) => Promise<void> | void
}

/**
 * Capability-aware Tools toggle. Pure presentational — mutex coordination
 * with reasoning happens in ``ReasoningToolsCluster``. Three states:
 *
 *   - tools not supported by model → disabled, "n/a"
 *   - supported, off              → idle, click to enable
 *   - supported, on               → active, click to disable
 *
 * The ``exclusive_with_reasoning`` flag is reflected in the disabled
 * tooltip so the user understands *why* a model cannot run tools (mutex
 * vs. truly unsupported), but the actual mutex enforcement is the
 * cluster's job.
 */
export function ToolsButton({ tools, enabled, availableGroups = [], onChange }: Props) {
  if (!tools.supported) {
    const label = tools.exclusive_with_reasoning
      ? 'Tools · n/a (mutex with reasoning)'
      : 'Tools · n/a'
    return (
      <CockpitButton
        icon="🔧"
        state="disabled"
        accent="silver"
        label={label}
        dataState="unsupported"
      />
    )
  }

  const label = enabled
    ? availableGroups.length > 0
      ? `Tools · on · ${availableGroups.length} available`
      : 'Tools · on'
    : 'Tools · off'

  return (
    <CockpitButton
      icon="🔧"
      state={enabled ? 'active' : 'idle'}
      accent="gold"
      label={label}
      onClick={() => {
        void onChange(!enabled)
      }}
      dataState={enabled ? 'active' : 'inactive'}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#d4af37] mb-2">
            Tools · {enabled ? 'on' : 'off'} · {availableGroups.length} available
          </div>
          {enabled ? (
            availableGroups.length > 0 ? (
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
            ) : (
              <p className="text-xs text-white/50">
                No tools wired up. Enable web search or connect an integration in persona settings.
              </p>
            )
          ) : (
            <p className="text-xs text-white/50">
              Toggle on to let the model call these tools.
            </p>
          )}
        </div>
      }
    />
  )
}
