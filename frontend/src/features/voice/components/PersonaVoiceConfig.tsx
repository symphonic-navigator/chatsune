import { useCallback, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import type { VoicePreset } from '../types'

interface Props {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
}

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

export function PersonaVoiceConfig({ persona, chakra, onSave }: Props) {
  const engine = ttsRegistry.active()
  const voices: VoicePreset[] = engine?.voices ?? []

  const [dialogueVoice, setDialogueVoice] = useState<string>(
    persona.voice_config?.dialogue_voice ?? ''
  )
  const [narratorVoice, setNarratorVoice] = useState<string>(
    persona.voice_config?.narrator_voice ?? ''
  )
  const [autoRead, setAutoRead] = useState<boolean>(
    persona.voice_config?.auto_read ?? false
  )
  const [roleplayMode, setRoleplayMode] = useState<boolean>(
    persona.voice_config?.roleplay_mode ?? false
  )
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState<'dialogue' | 'narrator' | null>(null)

  const persist = useCallback(async (patch: Partial<{
    dialogue_voice: string | null
    narrator_voice: string | null
    auto_read: boolean
    roleplay_mode: boolean
  }>) => {
    setSaving(true)
    try {
      await onSave(persona.id, {
        voice_config: {
          dialogue_voice: dialogueVoice || null,
          narrator_voice: narratorVoice || null,
          auto_read: autoRead,
          roleplay_mode: roleplayMode,
          ...patch,
        },
      })
    } finally {
      setSaving(false)
    }
  }, [persona.id, onSave, dialogueVoice, narratorVoice, autoRead, roleplayMode])

  const handleDialogueVoiceChange = useCallback(async (value: string) => {
    setDialogueVoice(value)
    await persist({ dialogue_voice: value || null })
  }, [persist])

  const handleNarratorVoiceChange = useCallback(async (value: string) => {
    setNarratorVoice(value)
    await persist({ narrator_voice: value || null })
  }, [persist])

  const handleAutoReadChange = useCallback(async (value: boolean) => {
    setAutoRead(value)
    await persist({ auto_read: value })
  }, [persist])

  const handleRoleplayModeChange = useCallback(async (value: boolean) => {
    setRoleplayMode(value)
    await persist({ roleplay_mode: value })
  }, [persist])

  const handlePreview = useCallback(async (slot: 'dialogue' | 'narrator') => {
    if (!engine || !engine.isReady()) return
    const voiceId = slot === 'dialogue' ? dialogueVoice : narratorVoice
    const preset = voices.find((v) => v.id === voiceId)
    if (!preset) return

    setPreviewing(slot)
    try {
      const sampleText = slot === 'dialogue'
        ? 'Hello, I am your companion. How can I help you today?'
        : 'The air was thick with anticipation as the story began to unfold.'
      const audio = await engine.synthesise(sampleText, preset)
      audioPlayback.enqueue(audio, { type: slot === 'narrator' ? 'narration' : 'voice', text: sampleText })
    } finally {
      setPreviewing(null)
    }
  }, [engine, dialogueVoice, narratorVoice, voices])

  const selectStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.03)',
    border: `1px solid ${chakra.hex}33`,
    borderRadius: '6px',
    color: 'rgba(255,255,255,0.8)',
    padding: '6px 10px',
    fontSize: '12px',
    fontFamily: 'inherit',
    width: '100%',
    outline: 'none',
  }

  if (voices.length === 0) {
    return (
      <div className="flex flex-col gap-4 p-6 max-w-xl">
        <p className="text-[11px] text-white/40 font-mono leading-relaxed">
          No TTS voices are loaded. Enable voice mode in Settings first, then return here to configure per-persona voice preferences.
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Configure how this persona speaks. Dialogue voice is used for the persona's words; narrator voice is used for narrated passages in roleplay mode.
      </p>

      {/* Dialogue Voice */}
      <div>
        <label className={LABEL}>Dialogue Voice</label>
        <div className="flex gap-2 items-center">
          <select
            style={selectStyle}
            value={dialogueVoice}
            disabled={saving}
            onChange={(e) => handleDialogueVoiceChange(e.target.value)}
          >
            <option value="" style={OPTION_STYLE}>— None —</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id} style={OPTION_STYLE}>
                {v.name}{v.gender ? ` (${v.gender})` : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!dialogueVoice || previewing !== null}
            onClick={() => handlePreview('dialogue')}
            className="px-3 py-1.5 rounded text-[11px] font-mono border border-white/10 text-white/50 hover:text-white/80 hover:border-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {previewing === 'dialogue' ? '…' : 'Preview'}
          </button>
        </div>
      </div>

      {/* Narrator Voice */}
      <div>
        <label className={LABEL}>Narrator Voice</label>
        <div className="flex gap-2 items-center">
          <select
            style={selectStyle}
            value={narratorVoice}
            disabled={saving}
            onChange={(e) => handleNarratorVoiceChange(e.target.value)}
          >
            <option value="" style={OPTION_STYLE}>— None —</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id} style={OPTION_STYLE}>
                {v.name}{v.gender ? ` (${v.gender})` : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!narratorVoice || previewing !== null}
            onClick={() => handlePreview('narrator')}
            className="px-3 py-1.5 rounded text-[11px] font-mono border border-white/10 text-white/50 hover:text-white/80 hover:border-white/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {previewing === 'narrator' ? '…' : 'Preview'}
          </button>
        </div>
      </div>

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
    </div>
  )
}
