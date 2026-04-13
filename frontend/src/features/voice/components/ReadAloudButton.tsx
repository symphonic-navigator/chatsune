import { useCallback, useState } from 'react'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { parseForSpeech } from '../pipeline/audioParser'
import type { VoicePreset } from '../types'

interface ReadAloudButtonProps {
  content: string
  dialogueVoice?: VoicePreset
  narratorVoice?: VoicePreset
  roleplayMode?: boolean
}

export function ReadAloudButton({ content, dialogueVoice, narratorVoice, roleplayMode = false }: ReadAloudButtonProps) {
  const [playing, setPlaying] = useState(false)

  const handleClick = useCallback(async () => {
    if (playing) { audioPlayback.stopAll(); setPlaying(false); return }
    const tts = ttsRegistry.active()
    if (!tts) return
    const fallbackVoice = tts.voices[0]
    const dVoice = dialogueVoice ?? fallbackVoice
    const nVoice = narratorVoice ?? fallbackVoice
    const segments = parseForSpeech(content, roleplayMode)
    if (segments.length === 0) return
    setPlaying(true)
    audioPlayback.setCallbacks({ onSegmentStart: () => {}, onFinished: () => setPlaying(false) })
    for (const segment of segments) {
      const voice = segment.type === 'voice' ? dVoice : nVoice
      const audio = await tts.synthesise(segment.text, voice)
      audioPlayback.enqueue(audio, segment)
    }
  }, [content, dialogueVoice, narratorVoice, roleplayMode, playing])

  return (
    <button type="button" onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${playing ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
      title={playing ? 'Stop reading' : 'Read aloud'}>
      {playing ? (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" /></svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
      )}
      {playing ? 'Stop' : 'Read'}
    </button>
  )
}
