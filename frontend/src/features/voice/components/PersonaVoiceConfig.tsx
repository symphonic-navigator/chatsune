import { useCallback, useEffect, useRef, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import { useIntegrationsStore } from '../../integrations/store'
import { useSecretsStore } from '../../integrations/secretsStore'
import { getPlugin } from '../../integrations/registry'
import { GenericConfigForm } from '../../integrations/components/GenericConfigForm'
import { resolveTTSEngine } from '../engines/resolver'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { setActiveReader } from './ReadAloudButton'
import { ModulationSlider } from './ModulationSlider'
import { resolveModulation, type VoiceModulation } from '../pipeline/applyModulation'
import type { NarratorMode, SpeechSegment } from '../types'
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
  const [testPhrase, setTestPhrase] = useState(PREVIEW_PHRASE)
  const [modulation, setModulation] = useState<VoiceModulation>(() =>
    resolveModulation(persona.voice_config),
  )
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Refs mirror the live state so `persistVoiceConfig` can stay stable across
  // re-renders. Without this the debounced `scheduleModulationSave` captures a
  // stale `persistVoiceConfig` whose closure holds OLD autoRead / narratorMode
  // / modulation values — when the timer fires after an intervening toggle
  // change, the stale snapshot silently reverts the toggle.
  const autoReadRef = useRef(autoRead)
  const narratorModeRef = useRef(narratorMode)
  const modulationRef = useRef(modulation)
  useEffect(() => { autoReadRef.current = autoRead }, [autoRead])
  useEffect(() => { narratorModeRef.current = narratorMode }, [narratorMode])
  useEffect(() => { modulationRef.current = modulation }, [modulation])

  const ttsProviders = definitions.filter(
    (d) => d.capabilities?.includes(TTS_PROVIDER) && configs?.[d.id]?.enabled,
  )
  const selectedProviderId =
    (persona.voice_config as { tts_provider_id?: string } | undefined)?.tts_provider_id
  const activeTTS = (selectedProviderId ? ttsProviders.find((d) => d.id === selectedProviderId) : undefined)
    ?? ttsProviders[0]
  const ttsPlugin = activeTTS ? getPlugin(activeTTS.id) : undefined
  const secrets = useSecretsStore((s) => s.secrets)

  const optionsProvider = useCallback(
    (fieldKey: string) =>
      ttsPlugin?.getPersonaConfigOptions?.(fieldKey) ?? Promise.resolve([]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ttsPlugin, secrets, activeTTS?.id],
  )

  const persistVoiceConfig = useCallback(
    async (patch: Partial<{
      auto_read: boolean
      narrator_mode: NarratorMode
      dialogue_speed: number
      dialogue_pitch: number
      narrator_speed: number
      narrator_pitch: number
      tts_provider_id: string | undefined
    }>) => {
      setSaving(true)
      try {
        const mod = modulationRef.current
        await onSave(persona.id, {
          voice_config: {
            dialogue_voice: persona.voice_config?.dialogue_voice ?? null,
            narrator_voice: persona.voice_config?.narrator_voice ?? null,
            auto_read: autoReadRef.current,
            narrator_mode: narratorModeRef.current,
            dialogue_speed: mod.dialogue_speed,
            dialogue_pitch: mod.dialogue_pitch,
            narrator_speed: mod.narrator_speed,
            narrator_pitch: mod.narrator_pitch,
            ...patch,
          },
        })
      } finally {
        setSaving(false)
      }
    },
    [persona.id, persona.voice_config, onSave],
  )

  const scheduleModulationSave = useCallback((next: VoiceModulation) => {
    setModulation(next)
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      void persistVoiceConfig(next)
    }, 400)
  }, [persistVoiceConfig])

  useEffect(() => {
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [])

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

  // Preview: synthesises testPhrase with the selected voice. Does not
  // participate in activeMessageId tracking; stopAll is always called first,
  // which cancels any ongoing read-aloud or earlier preview.
  const playPreview = useCallback(async (voiceId: string, isNarrator: boolean) => {
    const tts = resolveTTSEngine(persona)
    if (!tts?.isReady()) return
    const voice = tts.voices.find((v) => v.id === voiceId)
    if (!voice) return
    audioPlayback.stopAll()
    setActiveReader(null, 'idle')
    try {
      const audio = await tts.synthesise(testPhrase, voice)
      audioPlayback.setCallbacks({ onSegmentStart: () => {}, onFinished: () => {} })
      const speed = isNarrator ? modulation.narrator_speed : modulation.dialogue_speed
      const pitch = isNarrator ? modulation.narrator_pitch : modulation.dialogue_pitch
      const segType = isNarrator ? 'narration' : 'voice'
      const segment: SpeechSegment =
        speed === 1.0 && pitch === 0
          ? { type: segType, text: testPhrase }
          : { type: segType, text: testPhrase, speed, pitch }
      audioPlayback.enqueue(audio, segment)
    } catch (err) {
      console.error('[PersonaVoiceConfig] Preview failed:', err)
    }
  }, [testPhrase, modulation])

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
        {ttsProviders.length > 0 && (
          <div className="mb-4">
            <label className={LABEL}>TTS Provider</label>
            <select
              value={selectedProviderId ?? ''}
              onChange={(e) => {
                const newId = e.target.value || undefined
                void persistVoiceConfig({ tts_provider_id: newId })
              }}
              className="bg-white/5 text-[12px] font-mono text-white/80 rounded px-2 py-1 border border-white/10 focus:border-white/30 focus:outline-none w-full"
            >
              {ttsProviders.map((d) => (
                <option key={d.id} value={d.id} style={OPTION_STYLE}>
                  {d.display_name}{!selectedProviderId && d.id === ttsProviders[0]?.id ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </div>
        )}
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
            modulation={modulation}
            onModulationChange={scheduleModulationSave}
            chakra={chakra}
            testPhrase={testPhrase}
            onTestPhraseChange={setTestPhrase}
          />
        )}
      </div>
    </div>
  )
}

function VoiceFormWithPreview({
  activeTTS, persona, optionsProvider, onSave, playPreview, showNarratorField,
  modulation, onModulationChange, chakra, testPhrase, onTestPhraseChange,
}: {
  activeTTS: IntegrationDefinition
  persona: PersonaDto
  optionsProvider: (fieldKey: string) => Option[] | Promise<Option[]>
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
  playPreview: (voiceId: string, isNarrator: boolean) => Promise<void>
  showNarratorField: boolean
  modulation: VoiceModulation
  onModulationChange: (next: VoiceModulation) => void
  chakra: ChakraPaletteEntry
  testPhrase: string
  onTestPhraseChange: (s: string) => void
}) {
  const initial = (persona.integration_configs?.[activeTTS.id] ?? {}) as Record<string, unknown>
  const primaryId = initial.voice_id as string | undefined
  const narratorId = initial.narrator_voice_id as string | null | undefined

  const fields = activeTTS.persona_config_fields.filter(
    (f) => f.key !== 'narrator_voice_id' || showNarratorField,
  )

  const fmtSpeed = (v: number) => `${v.toFixed(2)}×`
  const fmtPitch = (v: number) => (v === 0 ? '0 st' : `${v > 0 ? '+' : ''}${v} st`)

  return (
    <div className="flex flex-col gap-4">
      <GenericConfigForm
        fields={fields}
        initialValues={initial}
        onSubmit={async (values) => {
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

      <div className="flex flex-col gap-3 pt-2 border-t border-white/10">
        <label className={LABEL}>Voice Modulation</label>

        {/* Snap to the 0.05 / 1-semitone grid — guards against FP drift from the range input. */}
        <div className="flex flex-col gap-3">
          <div className="text-[11px] text-white/55 font-mono">Primary voice</div>
          <ModulationSlider
            label="Speed" value={modulation.dialogue_speed} min={0.75} max={1.5} step={0.05}
            format={fmtSpeed} chakra={chakra}
            onChange={(v) => onModulationChange({ ...modulation, dialogue_speed: Math.round(v * 20) / 20 })}
          />
          <ModulationSlider
            label="Pitch" value={modulation.dialogue_pitch} min={-6} max={6} step={1}
            format={fmtPitch} chakra={chakra}
            onChange={(v) => onModulationChange({ ...modulation, dialogue_pitch: Math.round(v) })}
          />
        </div>

        {showNarratorField && (
          <div className="flex flex-col gap-3 mt-2">
            <div className="text-[11px] text-white/55 font-mono">Narrator voice</div>
            <ModulationSlider
              label="Speed" value={modulation.narrator_speed} min={0.75} max={1.5} step={0.05}
              format={fmtSpeed} chakra={chakra}
              onChange={(v) => onModulationChange({ ...modulation, narrator_speed: Math.round(v * 20) / 20 })}
            />
            <ModulationSlider
              label="Pitch" value={modulation.narrator_pitch} min={-6} max={6} step={1}
              format={fmtPitch} chakra={chakra}
              onChange={(v) => onModulationChange({ ...modulation, narrator_pitch: Math.round(v) })}
            />
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 pt-2 border-t border-white/10">
        <label className={LABEL}>Test phrase</label>
        <input
          type="text"
          value={testPhrase}
          onChange={(e) => onTestPhraseChange(e.target.value)}
          className="bg-white/5 text-[12px] font-mono text-white/80 rounded px-2 py-1.5 border border-white/10 focus:border-white/30 focus:outline-none"
        />
        {primaryId && (
          <PreviewButton label="Preview primary voice" onClick={() => playPreview(primaryId, false)} />
        )}
        {showNarratorField && narratorId && (
          <PreviewButton label="Preview narrator voice" onClick={() => playPreview(narratorId, true)} />
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
