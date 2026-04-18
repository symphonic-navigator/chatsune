import { useVoiceSettingsStore, type VoiceActivationThreshold } from '../../../features/voice/stores/voiceSettingsStore'

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'

const THRESHOLD_OPTIONS: { value: VoiceActivationThreshold; label: string }[] = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
]

export function VoiceTab() {
  const autoSend = useVoiceSettingsStore((s) => s.autoSendTranscription)
  const setAutoSend = useVoiceSettingsStore((s) => s.setAutoSendTranscription)
  const threshold = useVoiceSettingsStore((s) => s.voiceActivationThreshold)
  const setThreshold = useVoiceSettingsStore((s) => s.setVoiceActivationThreshold)

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
    </div>
  )
}
