import { useMemo, type CSSProperties } from 'react'
import { useMatch } from 'react-router-dom'
import { useVoiceSettingsStore, type VoiceActivationThreshold, type VisualiserStyle } from '../../../features/voice/stores/voiceSettingsStore'
import { useIntegrationsStore } from '../../../features/integrations/store'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { personaHex } from '../sidebar/personaColour'
import { VoiceVisualiserPreview } from '../../../features/voice/components/VoiceVisualiserPreview'

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'

const THRESHOLD_OPTIONS: { value: VoiceActivationThreshold; label: string }[] = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
]

const STT_PROVIDER = 'stt_provider'

const STYLE_OPTIONS: { value: VisualiserStyle; label: string }[] = [
  { value: 'sharp', label: 'Scharf' },
  { value: 'soft',  label: 'Weich' },
  { value: 'glow',  label: 'Glühend' },
  { value: 'glass', label: 'Glas' },
]

const OPTION_STYLE: CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

export function VoiceTab() {
  const autoSend = useVoiceSettingsStore((s) => s.autoSendTranscription)
  const setAutoSend = useVoiceSettingsStore((s) => s.setAutoSendTranscription)
  const threshold = useVoiceSettingsStore((s) => s.voiceActivationThreshold)
  const setThreshold = useVoiceSettingsStore((s) => s.setVoiceActivationThreshold)
  const sttProviderId = useVoiceSettingsStore((s) => s.stt_provider_id)
  const setSttProviderId = useVoiceSettingsStore((s) => s.setSttProviderId)

  const v = useVoiceSettingsStore((s) => s.visualisation)
  const setVisEnabled = useVoiceSettingsStore((s) => s.setVisualisationEnabled)
  const setVisStyle = useVoiceSettingsStore((s) => s.setVisualisationStyle)
  const setVisOpacity = useVoiceSettingsStore((s) => s.setVisualisationOpacity)
  const setVisBarCount = useVoiceSettingsStore((s) => s.setVisualisationBarCount)

  const chatMatch = useMatch('/chat/:personaId/:sessionId?')
  const activePersonaId = chatMatch?.params.personaId ?? null
  const { personas } = usePersonas()
  const activePersonaHex = activePersonaId
    ? personaHex(personas.find((p) => p.id === activePersonaId) ?? { colour_scheme: '' })
    : undefined

  const reducedMotion = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)
  const sttProviders = useMemo(
    () => definitions.filter((d) => d.capabilities?.includes(STT_PROVIDER) && configs?.[d.id]?.effective_enabled),
    [definitions, configs],
  )

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl overflow-y-auto">
      <div>
        <label className={LABEL}>Automatically send transcription</label>
        <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
          When on, your transcribed speech is sent as soon as you release
          Push-to-Talk — no extra tap.
        </p>
        <button
          type="button"
          aria-label="Automatically send transcription"
          onClick={() => setAutoSend(!autoSend)}
          className={[
            'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            autoSend
              ? 'border-gold/60 bg-gold/12 text-gold'
              : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}
        >
          {autoSend ? 'On' : 'Off'}
        </button>
      </div>

      <div>
        <label className={LABEL}>Voice Activation Threshold</label>
        <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
          Controls how sensitive conversational mode is to incoming sound.
          Low picks up the quietest speech but also coughs, keyboard clicks
          and sips of coffee. High ignores more background noise and only
          triggers on clear, sustained speech.
        </p>
        <div className="flex gap-2">
          {THRESHOLD_OPTIONS.map((opt) => {
            const active = threshold === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                aria-label={`Voice Activation Threshold ${opt.label}`}
                aria-pressed={active}
                onClick={() => setThreshold(opt.value)}
                className={[
                  'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
                  active
                    ? 'border-gold/60 bg-gold/12 text-gold'
                    : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
                ].join(' ')}
              >
                {opt.label}
              </button>
            )
          })}
        </div>
      </div>

      {sttProviders.length > 0 && (
        <div>
          <label className={LABEL}>Voice Input Provider</label>
          <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
            Used across all personas and chat inputs when you speak to Chatsune.
          </p>
          <select
            value={sttProviderId ?? ''}
            onChange={(e) => setSttProviderId(e.target.value || undefined)}
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm focus:border-gold/30 focus:outline-none"
          >
            {sttProviders.map((d) => (
              <option key={d.id} value={d.id} style={OPTION_STYLE}>
                {d.display_name}{!sttProviderId && d.id === sttProviders[0]?.id ? ' (default)' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="border-t border-white/10 pt-6">
        <h3 className="text-sm uppercase tracking-[0.15em] text-white/70 font-mono mb-4">
          Sprachausgabe-Visualisierung
        </h3>

        <label className="flex items-center gap-3 mb-4">
          <input
            type="checkbox"
            checked={v.enabled}
            onChange={(e) => setVisEnabled(e.target.checked)}
          />
          <span className="text-sm text-white/85">Visualisierung anzeigen</span>
        </label>

        {reducedMotion && (
          <p className="text-[11px] text-amber-300/80 font-mono mb-4 leading-relaxed">
            Dein Betriebssystem hat „Bewegung reduzieren" aktiviert — die Visualisierung ist deaktiviert.
          </p>
        )}

        <div className={v.enabled ? '' : 'opacity-40 pointer-events-none'}>
          <label className={LABEL}>Stil</label>
          <div className="flex gap-2 mb-4 flex-wrap">
            {STYLE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setVisStyle(opt.value)}
                className={
                  'px-3 py-1.5 rounded-md text-xs font-mono border ' +
                  (v.style === opt.value
                    ? 'bg-white/10 border-white/40 text-white'
                    : 'bg-white/[0.03] border-white/10 text-white/65 hover:border-white/25')
                }
              >
                {opt.label}
              </button>
            ))}
          </div>

          <label className={LABEL} htmlFor="vis-opacity">
            Deckkraft <span className="text-white/85">{Math.round(v.opacity * 100)}%</span>
          </label>
          <input
            id="vis-opacity"
            type="range"
            min={5}
            max={80}
            value={Math.round(v.opacity * 100)}
            onChange={(e) => setVisOpacity(Number(e.target.value) / 100)}
            className="w-full mb-4 accent-white/70"
          />

          <label className={LABEL} htmlFor="vis-bar-count">
            Anzahl Säulen <span className="text-white/85">{v.barCount}</span>
          </label>
          <input
            id="vis-bar-count"
            type="range"
            min={16}
            max={96}
            value={v.barCount}
            onChange={(e) => setVisBarCount(Number(e.target.value))}
            className="w-full mb-4 accent-white/70"
          />

          <VoiceVisualiserPreview
            style={v.style}
            opacity={v.opacity}
            barCount={v.barCount}
            enabled={v.enabled}
            personaColourHex={activePersonaHex}
          />
        </div>
      </div>
    </div>
  )
}
