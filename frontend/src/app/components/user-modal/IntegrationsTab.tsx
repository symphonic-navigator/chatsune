import { useEffect, useState, useCallback } from 'react'
import { useIntegrationsStore } from '../../../features/integrations/store'
import { getPlugin } from '../../../features/integrations/registry'
import { GenericConfigForm } from '../../../features/integrations/components/GenericConfigForm'
import type { IntegrationDefinition } from '../../../features/integrations/types'

// Ensure plugins are registered
import '../../../features/integrations/plugins/lovense'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

function IntegrationCard({ definition }: { definition: IntegrationDefinition }) {
  const { configs, upsertConfig, healthStatus, setHealth } = useIntegrationsStore()
  const config = configs[definition.id]
  const enabled = config?.enabled ?? false
  const userConfig = config?.config ?? {}
  const health = healthStatus[definition.id] ?? 'unknown'

  // localConfig is only used by the full-replacement ConfigComponent path (e.g. Lovense).
  const [localConfig, setLocalConfig] = useState<Record<string, unknown>>(userConfig)
  const [saving, setSaving] = useState(false)

  // Sync local config when store changes
  useEffect(() => {
    setLocalConfig(config?.config ?? {})
  }, [config])

  const handleToggle = useCallback(async () => {
    setSaving(true)
    try {
      await upsertConfig(definition.id, !enabled, localConfig)
    } finally {
      setSaving(false)
    }
  }, [definition.id, enabled, localConfig, upsertConfig])

  const handleSaveConfig = useCallback(async () => {
    setSaving(true)
    try {
      await upsertConfig(definition.id, enabled, localConfig)
    } finally {
      setSaving(false)
    }
  }, [definition.id, enabled, localConfig, upsertConfig])

  // Health check when enabled
  useEffect(() => {
    if (!enabled) {
      setHealth(definition.id, 'unknown')
      return
    }
    const plugin = getPlugin(definition.id)
    if (!plugin?.healthCheck) return

    const configSnapshot = config?.config ?? {}
    let cancelled = false
    plugin.healthCheck(configSnapshot).then((status) => {
      if (!cancelled) setHealth(definition.id, status)
    })
    return () => { cancelled = true }
  }, [enabled, definition.id, config, setHealth])

  const plugin = getPlugin(definition.id)
  const ConfigUI = plugin?.ConfigComponent
  const ExtraUI = plugin?.ExtraConfigComponent

  const configDirty = JSON.stringify(localConfig) !== JSON.stringify(userConfig)

  const healthDot = (() => {
    if (!enabled) return null
    switch (health) {
      case 'connected': return <span className="inline-block w-2 h-2 rounded-full bg-green-400" title="Connected" />
      case 'reachable': return <span className="inline-block w-2 h-2 rounded-full bg-yellow-400" title="Reachable (no toys)" />
      case 'unreachable': return <span className="inline-block w-2 h-2 rounded-full bg-red-400" title="Unreachable" />
      default: return <span className="inline-block w-2 h-2 rounded-full bg-white/20" title="Unknown" />
    }
  })()

  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.02] p-4">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold text-white/80">{definition.display_name}</span>
          {healthDot}
        </div>
        <button
          type="button"
          onClick={handleToggle}
          disabled={saving}
          className={[
            'px-3 py-1 rounded-full text-[10px] font-mono uppercase tracking-wider transition-all border',
            enabled
              ? 'border-green-500/40 bg-green-500/15 text-green-400'
              : 'border-white/15 bg-white/5 text-white/40 hover:text-white/60',
          ].join(' ')}
        >
          {enabled ? 'On' : 'Off'}
        </button>
      </div>

      <p className="text-[11px] text-white/40 font-mono leading-relaxed mb-3">{definition.description}</p>

      {/* Config UI (only when enabled) */}
      {enabled && (
        <div className="mt-3 pt-3 border-t border-white/6">
          <label className={LABEL}>Configuration</label>
          {ConfigUI ? (
            // Full-replacement custom config (e.g. Lovense pairing flow)
            <>
              <ConfigUI config={localConfig} onChange={setLocalConfig} />
              {configDirty && (
                <button
                  type="button"
                  onClick={handleSaveConfig}
                  disabled={saving}
                  className="mt-3 px-4 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-wider border border-gold/60 bg-gold/12 text-gold hover:bg-gold/20 transition-all"
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>
              )}
            </>
          ) : (
            // Generic config form driven by the integration's config_fields
            <>
              {definition.config_fields.length > 0 ? (
                <GenericConfigForm
                  fields={definition.config_fields}
                  initialValues={userConfig}
                  onSubmit={async (values) => {
                    await upsertConfig(definition.id, enabled, values)
                  }}
                  optionsProvider={(fieldKey) => plugin?.getPersonaConfigOptions?.(fieldKey) ?? []}
                />
              ) : (
                <p className="text-[11px] text-white/30 font-mono">No configuration required.</p>
              )}
              {ExtraUI && <ExtraUI />}
            </>
          )}
        </div>
      )}

      {/* Feature badges */}
      <div className="flex gap-2 mt-3">
        {definition.has_response_tags && (
          <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">Tags</span>
        )}
        {definition.has_tools && (
          <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">Tools</span>
        )}
        {definition.has_prompt_extension && (
          <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">Prompt</span>
        )}
        <span className="text-[9px] font-mono uppercase text-white/30 border border-white/10 rounded px-1.5 py-0.5">{definition.execution_mode}</span>
      </div>
    </div>
  )
}


export function IntegrationsTab() {
  const { definitions, loaded, load } = useIntegrationsStore()

  useEffect(() => {
    if (!loaded) load()
  }, [loaded, load])

  if (!loaded) {
    return (
      <div className="p-6">
        <p className="text-[11px] text-white/40 font-mono">Loading integrations...</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6 max-w-xl overflow-y-auto">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Enable integrations to let your personas interact with local services
        and devices. Each integration must also be assigned to a persona to
        become active in chat.
      </p>

      {definitions.length === 0 ? (
        <p className="text-[11px] text-white/30 font-mono">No integrations available.</p>
      ) : (
        definitions.map((d) => <IntegrationCard key={d.id} definition={d} />)
      )}
    </div>
  )
}
