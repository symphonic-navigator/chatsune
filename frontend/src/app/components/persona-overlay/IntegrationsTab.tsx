import { useState, useEffect, useCallback } from 'react'
import { useIntegrationsStore } from '../../../features/integrations/store'
import type { PersonaDto } from '../../../core/types/persona'

import '../../../features/integrations/plugins/lovense'
import '../../../features/integrations/plugins/mistral_voice'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

interface Props {
  persona: PersonaDto
  onSave: (personaId: string, data: Record<string, unknown>) => Promise<void>
}

export function IntegrationsTab({ persona, onSave }: Props) {
  const { definitions, configs, loaded, load } = useIntegrationsStore()
  const [enabledIds, setEnabledIds] = useState<string[]>(
    persona.integrations_config?.enabled_integration_ids ?? []
  )
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  const availableDefs = definitions.filter(
    (d) => configs[d.id]?.effective_enabled && d.capabilities?.includes('tool_provider')
  )

  const handleToggle = useCallback(async (id: string) => {
    const next = enabledIds.includes(id)
      ? enabledIds.filter((x) => x !== id)
      : [...enabledIds, id]
    setEnabledIds(next)

    setSaving(true)
    try {
      await onSave(persona.id, {
        integrations_config: { enabled_integration_ids: next },
      })
    } finally {
      setSaving(false)
    }
  }, [persona.id, enabledIds, onSave])

  if (!loaded) {
    return <div className="p-6"><p className="text-[11px] text-white/40 font-mono">Loading...</p></div>
  }

  return (
    <div className="flex flex-col gap-4 p-6 max-w-xl overflow-y-auto">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Choose which integrations this persona can use during chat.
        Only integrations that are enabled in your user settings appear here.
      </p>

      {availableDefs.length === 0 ? (
        <p className="text-[11px] text-white/30 font-mono">
          No integrations enabled. Enable them in your user settings first.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <label className={LABEL}>Available Integrations</label>
          {availableDefs.map((d) => {
            const active = enabledIds.includes(d.id)
            return (
              <button
                key={d.id}
                type="button"
                disabled={saving}
                onClick={() => handleToggle(d.id)}
                className={[
                  'flex items-center gap-3 px-4 py-2.5 rounded-lg border text-left transition-all',
                  saving ? 'opacity-50 cursor-wait' : '',
                  active
                    ? 'border-gold/40 bg-gold/8 text-gold'
                    : 'border-white/8 bg-white/[0.02] text-white/50 hover:text-white/70 hover:border-white/15',
                ].join(' ')}
              >
                <span className={[
                  'w-3 h-3 rounded-sm border flex items-center justify-center transition-all',
                  active ? 'border-gold/60 bg-gold/20' : 'border-white/20',
                ].join(' ')}>
                  {active && (
                    <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                      <path d="M1.5 4L3 5.5L6.5 2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
                <div>
                  <span className="text-[12px] font-mono">{d.display_name}</span>
                  <span className="text-[10px] text-white/30 ml-2">{d.description}</span>
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
