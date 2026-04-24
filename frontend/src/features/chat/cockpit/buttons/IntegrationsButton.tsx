import { CockpitButton } from '../CockpitButton'
import { useIntegrationsStore } from '@/features/integrations/store'
import { getPlugin } from '@/features/integrations/registry'

type Props = {
  activePersonaIntegrationIds: string[]
}

export function IntegrationsButton({ activePersonaIntegrationIds }: Props) {
  const configs = useIntegrationsStore((s) => s.configs)
  const health = useIntegrationsStore((s) => s.healthStatus)

  const active = activePersonaIntegrationIds
    .map((id) => configs[id])
    .filter((c): c is NonNullable<typeof c> => Boolean(c))

  const stopOne = (integrationId: string) => {
    const plugin = getPlugin(integrationId)
    const cfg = configs[integrationId]?.config ?? {}
    if (plugin?.emergencyStop) {
      plugin.emergencyStop(cfg).catch(() => {
        // Best-effort stop — swallow errors
      })
    }
  }

  const stopAll = () => {
    for (const c of active) stopOne(c.integration_id)
  }

  if (active.length === 0) {
    return (
      <CockpitButton
        icon="🔌"
        state="disabled"
        accent="purple"
        label="No integrations active"
        panel={
          <p className="text-white/70">
            No integrations active. Connect e.g. Lovense in persona settings.
          </p>
        }
      />
    )
  }

  return (
    <CockpitButton
      icon="🔌"
      state="active"
      accent="purple"
      label={`${active.length} integration${active.length === 1 ? '' : 's'} active`}
      panel={
        <div className="text-white/85">
          <div className="text-[10px] uppercase tracking-wider text-white/40 mb-2">
            Active integrations
          </div>
          {active.map((config) => {
            const status = health[config.integration_id]
            const healthy = status === 'connected' || status === 'reachable'
            return (
              <div
                key={config.integration_id}
                className="flex items-center justify-between py-2 border-b border-white/5 last:border-b-0"
              >
                <div>
                  <div>{config.integration_id}</div>
                  <div className="text-[10px] text-[#4ade80]/80">
                    {healthy ? '● connected · healthy' : '○ check connection'}
                  </div>
                </div>
                <button
                  type="button"
                  className="text-[11px] px-2 py-1 rounded border border-red-500/40 bg-red-500/15 text-red-300"
                  onClick={() => stopOne(config.integration_id)}
                >
                  Stop
                </button>
              </div>
            )
          })}
          <button
            type="button"
            className="w-full text-xs mt-3 px-3 py-2 rounded border border-red-500/45 bg-red-500/20 text-red-200"
            onClick={stopAll}
          >
            Emergency stop — all
          </button>
        </div>
      }
    />
  )
}
