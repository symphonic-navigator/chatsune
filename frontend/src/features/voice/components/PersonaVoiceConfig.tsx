import { useCallback, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import { useIntegrationsStore } from '../../integrations/store'
import { useSecretsStore } from '../../integrations/secretsStore'
import { getPlugin } from '../../integrations/registry'
import { GenericConfigForm } from '../../integrations/components/GenericConfigForm'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { setActiveReader } from './ReadAloudButton'
import type { NarratorMode } from '../types'
import type { IntegrationDefinition, Option } from '../../integrations/types'

interface Props {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
}

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'
const TTS_PROVIDER = 'tts_provider'
const PREVIEW_PHRASE = 'The quick brown fox jumps over the lazy dog.'

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

const MODE_LABELS: Record<NarratorMode, string> = {
  off: 'Off',
  play: 'Roleplay (dialogue spoken)',
  narrate: 'Narrated (narration spoken)',
}

export function PersonaVoiceConfig({ persona, chakra, onSave }: Props) {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const [autoRead, setAutoRead] = useState<boolean>(
    persona.voice_config?.auto_read ?? false,
  )
  const [narratorMode, setNarratorMode] = useState<NarratorMode>(
    persona.voice_config?.narrator_mode ?? 'off',
  )
  const [saving, setSaving] = useState(false)

  const activeTTS = definitions.find(
    (d) => d.capabilities?.includes(TTS_PROVIDER) && configs?.[d.id]?.enabled,
  )
  const ttsPlugin = activeTTS ? getPlugin(activeTTS.id) : undefined
  const secrets = useSecretsStore((s) => s.secrets)

  const optionsProvider = useCallback(
    (fieldKey: string) =>
      ttsPlugin?.getPersonaConfigOptions?.(fieldKey) ?? Promise.resolve([]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ttsPlugin, secrets],
  )

  const persistVoiceConfig = useCallback(
    async (patch: Partial<{ auto_read: boolean; narrator_mode: NarratorMode }>) => {
      setSaving(true)
      try {
        await onSave(persona.id, {
          voice_config: {
            dialogue_voice: persona.voice_config?.dialogue_voice ?? null,
            narrator_voice: persona.voice_config?.narrator_voice ?? null,
            auto_read: autoRead,
            narrator_mode: narratorMode,
            ...patch,
          },
        })
      } finally {
        setSaving(false)
      }
    },
    [persona.id, persona.voice_config, onSave, autoRead, narratorMode],
  )

  const handleAutoReadChange = useCallback(
    async (value: boolean) => {
      setAutoRead(value)
      await persistVoiceConfig({ auto_read: value })
    },
    [persistVoiceConfig],
  )

  const handleModeChange = useCallback(
    async (value: NarratorMode) => {
      setNarratorMode(value)
      await persistVoiceConfig({ narrator_mode: value })
    },
    [persistVoiceConfig],
  )

  // Preview: synthesises PREVIEW_PHRASE with the selected voice. Does not
  // participate in activeMessageId tracking; stopAll is always called first,
  // which cancels any ongoing read-aloud or earlier preview.
  const playPreview = useCallback(async (voiceId: string) => {
    const tts = ttsRegistry.active()
    if (!tts?.isReady()) return
    const voice = tts.voices.find((v) => v.id === voiceId)
    if (!voice) return
    audioPlayback.stopAll()
    setActiveReader(null, 'idle')
    try {
      const audio = await tts.synthesise(PREVIEW_PHRASE, voice)
      audioPlayback.setCallbacks({ onSegmentStart: () => {}, onFinished: () => {} })
      audioPlayback.enqueue(audio, { type: 'voice', text: PREVIEW_PHRASE })
    } catch (err) {
      console.error('[PersonaVoiceConfig] Preview failed:', err)
    }
  }, [])

  const showNarratorField = narratorMode !== 'off'

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Configure how this persona speaks. Enable a TTS integration and select a voice below.
      </p>

      <div className="flex flex-col gap-4">
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
            style={{ width: 44, height: 20, background: autoRead ? chakra.hex : 'rgba(255,255,255,0.1)' }}
          >
            <span
              className="absolute top-[2px] rounded-full bg-white shadow transition-transform duration-200"
              style={{ width: 16, height: 16, left: 2, transform: autoRead ? 'translateX(24px)' : 'translateX(0)' }}
            />
          </button>
        </div>

        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <span className="text-[12px] text-white/70 font-mono">Narrator Mode</span>
            <p className="text-[10px] text-white/35 font-mono mt-0.5">
              Split prose and dialogue into two voices.
            </p>
          </div>
          <select
            value={narratorMode}
            disabled={saving}
            onChange={(e) => handleModeChange(e.target.value as NarratorMode)}
            className="bg-white/5 text-[12px] font-mono text-white/80 rounded px-2 py-1 border border-white/10 focus:border-white/30 focus:outline-none disabled:opacity-50"
          >
            <option value="off" style={OPTION_STYLE}>{MODE_LABELS.off}</option>
            <option value="play" style={OPTION_STYLE}>{MODE_LABELS.play}</option>
            <option value="narrate" style={OPTION_STYLE}>{MODE_LABELS.narrate}</option>
          </select>
        </div>
      </div>

      <div>
        <label className={LABEL}>Voice</label>
        {!activeTTS && (
          <p className="text-[11px] text-white/40 font-mono leading-relaxed">
            Activate a TTS integration under Settings → Integrations to select a voice for this persona.
          </p>
        )}
        {activeTTS && (
          <VoiceFormWithPreview
            activeTTS={activeTTS}
            persona={persona}
            optionsProvider={optionsProvider}
            onSave={onSave}
            playPreview={playPreview}
            showNarratorField={showNarratorField}
          />
        )}
      </div>
    </div>
  )
}

function VoiceFormWithPreview({
  activeTTS, persona, optionsProvider, onSave, playPreview, showNarratorField,
}: {
  activeTTS: IntegrationDefinition
  persona: PersonaDto
  optionsProvider: (fieldKey: string) => Option[] | Promise<Option[]>
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
  playPreview: (voiceId: string) => Promise<void>
  showNarratorField: boolean
}) {
  const initial = (persona.integration_configs?.[activeTTS.id] ?? {}) as Record<string, unknown>
  const primaryId = initial.voice_id as string | undefined
  const narratorId = initial.narrator_voice_id as string | null | undefined

  const fields = activeTTS.persona_config_fields.filter(
    (f) => f.key !== 'narrator_voice_id' || showNarratorField,
  )

  return (
    <div className="flex flex-col gap-2">
      <GenericConfigForm
        fields={fields}
        initialValues={initial}
        onSubmit={async (values) => {
          // GenericConfigForm emits '' for the Inherit option (whose source
          // value is null). Coerce it back to null before persisting so the
          // stored document honours the null = inherit contract.
          const normalised: Record<string, unknown> = { ...values }
          if ('narrator_voice_id' in normalised && normalised.narrator_voice_id === '') {
            normalised.narrator_voice_id = null
          }
          await onSave(persona.id, {
            integration_configs: {
              ...(persona.integration_configs ?? {}),
              [activeTTS.id]: normalised,
            },
          })
        }}
        optionsProvider={optionsProvider}
        submitLabel="Save voice"
        autoSubmit
      />
      <div className="flex flex-col gap-2 mt-1">
        {primaryId && (
          <PreviewButton label="Preview primary voice" onClick={() => playPreview(primaryId)} />
        )}
        {showNarratorField && narratorId && (
          <PreviewButton label="Preview narrator voice" onClick={() => playPreview(narratorId)} />
        )}
      </div>
    </div>
  )
}

function PreviewButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 self-start text-[10px] font-mono text-white/45 hover:text-white/75 transition-colors"
    >
      <svg width="11" height="11" viewBox="0 0 14 14" fill="none">
        <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
        <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      </svg>
      {label}
    </button>
  )
}
