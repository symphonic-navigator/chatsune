import { useCallback, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import { useIntegrationsStore } from '../../integrations/store'
import { useSecretsStore } from '../../integrations/secretsStore'
import { getPlugin } from '../../integrations/registry'
import { GenericConfigForm } from '../../integrations/components/GenericConfigForm'

interface Props {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
}

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'

const TTS_PROVIDER = 'tts_provider'

export function PersonaVoiceConfig({ persona, chakra, onSave }: Props) {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const [autoRead, setAutoRead] = useState<boolean>(
    persona.voice_config?.auto_read ?? false,
  )
  const [roleplayMode, setRoleplayMode] = useState<boolean>(
    persona.voice_config?.roleplay_mode ?? false,
  )
  const [saving, setSaving] = useState(false)

  // Find the first enabled TTS integration
  const activeTTS = definitions.find(
    (d) =>
      d.capabilities?.includes(TTS_PROVIDER) &&
      configs?.[d.id]?.enabled,
  )

  const ttsPlugin = activeTTS ? getPlugin(activeTTS.id) : undefined

  console.log('[PVC] definitionsCount =', definitions.length)
  console.log('[PVC] configsKeys =', Object.keys(configs ?? {}))
  console.log('[PVC] activeTTS.id =', activeTTS?.id)
  console.log('[PVC] activeTTS.capabilities =', activeTTS?.capabilities)
  console.log('[PVC] activeTTS.persona_config_fields =', JSON.stringify(activeTTS?.persona_config_fields))
  console.log('[PVC] ttsPlugin.id =', ttsPlugin?.id)
  console.log('[PVC] ttsPlugin.hasGetOptions =', typeof ttsPlugin?.getPersonaConfigOptions === 'function')
  console.log('[PVC] ttsPlugin keys =', ttsPlugin ? Object.keys(ttsPlugin) : 'NO PLUGIN')

  // Subscribe to secrets so optionsProvider gets a new identity when secrets
  // are hydrated — this triggers SelectField's useEffect to re-fetch the list.
  const secrets = useSecretsStore((s) => s.secrets)

  const optionsProvider = useCallback(
    (fieldKey: string) =>
      ttsPlugin?.getPersonaConfigOptions?.(fieldKey) ?? Promise.resolve([]),
    // secrets in deps forces re-identity when secrets are hydrated
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ttsPlugin, secrets],
  )

  const persistVoiceConfig = useCallback(
    async (patch: Partial<{ auto_read: boolean; roleplay_mode: boolean }>) => {
      setSaving(true)
      try {
        await onSave(persona.id, {
          voice_config: {
            dialogue_voice: persona.voice_config?.dialogue_voice ?? null,
            narrator_voice: persona.voice_config?.narrator_voice ?? null,
            auto_read: autoRead,
            roleplay_mode: roleplayMode,
            ...patch,
          },
        })
      } finally {
        setSaving(false)
      }
    },
    [persona.id, persona.voice_config, onSave, autoRead, roleplayMode],
  )

  const handleAutoReadChange = useCallback(
    async (value: boolean) => {
      setAutoRead(value)
      await persistVoiceConfig({ auto_read: value })
    },
    [persistVoiceConfig],
  )

  const handleRoleplayModeChange = useCallback(
    async (value: boolean) => {
      setRoleplayMode(value)
      await persistVoiceConfig({ roleplay_mode: value })
    },
    [persistVoiceConfig],
  )

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Configure how this persona speaks. Enable a TTS integration and select a voice below.
      </p>

      {/* Toggles */}
      <div className="flex flex-col gap-4">
        {/* Roleplay Mode */}
        <div className="flex items-center justify-between">
          <div>
            <span className="text-[12px] text-white/70 font-mono">Roleplay Mode</span>
            <p className="text-[10px] text-white/35 font-mono mt-0.5">
              Split narration and dialogue into separate voices.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={roleplayMode}
            disabled={saving}
            onClick={() => handleRoleplayModeChange(!roleplayMode)}
            className="relative flex-shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50"
            style={{
              width: 44,
              height: 20,
              background: roleplayMode ? chakra.hex : 'rgba(255,255,255,0.1)',
            }}
          >
            <span
              className="absolute top-[2px] rounded-full bg-white shadow transition-transform duration-200"
              style={{
                width: 16,
                height: 16,
                left: 2,
                transform: roleplayMode ? 'translateX(24px)' : 'translateX(0)',
              }}
            />
          </button>
        </div>

        {/* Auto-Read */}
        <div className="flex items-center justify-between">
          <div>
            <span className="text-[12px] text-white/70 font-mono">Auto-Read Replies</span>
            <p className="text-[10px] text-white/35 font-mono mt-0.5">
              Automatically speak each reply as it arrives.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={autoRead}
            disabled={saving}
            onClick={() => handleAutoReadChange(!autoRead)}
            className="relative flex-shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50"
            style={{
              width: 44,
              height: 20,
              background: autoRead ? chakra.hex : 'rgba(255,255,255,0.1)',
            }}
          >
            <span
              className="absolute top-[2px] rounded-full bg-white shadow transition-transform duration-200"
              style={{
                width: 16,
                height: 16,
                left: 2,
                transform: autoRead ? 'translateX(24px)' : 'translateX(0)',
              }}
            />
          </button>
        </div>
      </div>

      {/* Voice selection — driven by active TTS integration */}
      <div>
        <label className={LABEL}>Voice</label>
        {!activeTTS && (
          <p className="text-[11px] text-white/40 font-mono leading-relaxed">
            Activate a TTS integration under Settings → Integrations to select a voice for this persona.
          </p>
        )}
        {activeTTS && (
          <GenericConfigForm
            fields={activeTTS.persona_config_fields}
            initialValues={persona.integration_configs?.[activeTTS.id] ?? {}}
            onSubmit={async (values) => {
              await onSave(persona.id, {
                integration_configs: {
                  ...(persona.integration_configs ?? {}),
                  [activeTTS.id]: values,
                },
              })
            }}
            optionsProvider={optionsProvider}
            submitLabel="Save voice"
            autoSubmit
          />
        )}
      </div>
    </div>
  )
}
