import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

export function VoiceSettings() {
  const inputMode = useVoiceSettingsStore((s) => s.inputMode)
  const setInputMode = useVoiceSettingsStore((s) => s.setInputMode)

  return (
    <div>
      <label className={LABEL}>Input Mode</label>
      <div className="flex gap-1.5">
        <button type="button" onClick={() => setInputMode('push-to-talk')}
          className={['px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            inputMode === 'push-to-talk' ? 'border-gold/60 bg-gold/12 text-gold' : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}>Push-to-Talk</button>
        <button type="button" onClick={() => setInputMode('continuous')}
          className={['px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            inputMode === 'continuous' ? 'border-gold/60 bg-gold/12 text-gold' : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}>Continuous</button>
      </div>
    </div>
  )
}
