import { useVoiceSettings } from '../stores/voiceSettingsStore'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

export function VoiceSettings() {
  const { settings, update } = useVoiceSettings()

  return (
    <>
      <div>
        <label className={LABEL}>Voice Mode</label>
        <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
          Enable speech recognition and text-to-speech.
        </p>
        <button type="button" onClick={() => update({ enabled: !settings.enabled })}
          className={['px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            settings.enabled ? 'border-gold/60 bg-gold/12 text-gold' : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}>
          {settings.enabled ? 'On' : 'Off'}
        </button>
      </div>
      {settings.enabled && (
        <div>
          <label className={LABEL}>Input Mode</label>
          <div className="flex gap-1.5">
            <button type="button" onClick={() => update({ inputMode: 'push-to-talk' })}
              className={['px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
                settings.inputMode === 'push-to-talk' ? 'border-gold/60 bg-gold/12 text-gold' : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
              ].join(' ')}>Push-to-Talk</button>
            <button type="button" onClick={() => update({ inputMode: 'continuous' })}
              className={['px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
                settings.inputMode === 'continuous' ? 'border-gold/60 bg-gold/12 text-gold' : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
              ].join(' ')}>Continuous</button>
          </div>
        </div>
      )}
    </>
  )
}
