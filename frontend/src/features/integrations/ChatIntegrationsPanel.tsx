import { useIntegrationsStore } from './store'
import { getPlugin } from './registry'

import './plugins/lovense'

export function ChatIntegrationsPanel() {
  const { definitions, configs, healthStatus } = useIntegrationsStore()

  const enabledDefs = definitions.filter((d) => configs[d.id]?.enabled)

  if (enabledDefs.length === 0) return null

  const handleEmergencyStop = async () => {
    for (const d of enabledDefs) {
      const plugin = getPlugin(d.id)
      const config = configs[d.id]?.config ?? {}
      if (plugin?.emergencyStop) {
        try {
          await plugin.emergencyStop(config)
        } catch {
          // Best-effort stop
        }
      }
    }
  }

  return (
    <div className="flex items-center gap-2">
      {enabledDefs.map((d) => {
        const health = healthStatus[d.id] ?? 'unknown'
        const dotColour = health === 'connected' ? 'bg-green-400'
          : health === 'reachable' ? 'bg-yellow-400'
          : health === 'unreachable' ? 'bg-red-400'
          : 'bg-white/20'

        return (
          <span
            key={d.id}
            className="flex items-center gap-1.5 px-2 py-1 rounded border border-white/10 bg-white/[0.03] text-[10px] font-mono text-white/50"
            title={`${d.display_name}: ${health}`}
          >
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotColour}`} />
            {d.display_name}
          </span>
        )
      })}

      <button
        type="button"
        onClick={handleEmergencyStop}
        className="flex h-6 w-6 items-center justify-center rounded border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
        title="Emergency stop all integrations"
        aria-label="Emergency stop"
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
          <rect x="1" y="1" width="8" height="8" rx="1" />
        </svg>
      </button>
    </div>
  )
}
