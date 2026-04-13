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

type ReadState = 'idle' | 'synthesising' | 'playing'

export function ReadAloudButton({ content, dialogueVoice, narratorVoice, roleplayMode = false }: ReadAloudButtonProps) {
  const [state, setState] = useState<ReadState>('idle')

  const handleClick = useCallback(async () => {
    if (state === 'playing' || state === 'synthesising') {
      audioPlayback.stopAll()
      setState('idle')
      return
    }
    const tts = ttsRegistry.active()
    if (!tts) {
      console.warn('[ReadAloud] No TTS engine active — complete voice setup first')
      return
    }
    const fallbackVoice = tts.voices[0]
    const dVoice = dialogueVoice ?? fallbackVoice
    const nVoice = narratorVoice ?? fallbackVoice
    const segments = parseForSpeech(content, roleplayMode)
    if (segments.length === 0) return

    setState('synthesising')
    audioPlayback.setCallbacks({
      onSegmentStart: () => setState('playing'),
      onFinished: () => setState('idle'),
    })

    try {
      for (const segment of segments) {
        const voice = segment.type === 'voice' ? dVoice : nVoice
        const audio = await tts.synthesise(segment.text, voice)
        audioPlayback.enqueue(audio, segment)
      }
    } catch (err) {
      console.error('[ReadAloud] TTS synthesis failed:', err)
      setState('idle')
    }
  }, [content, dialogueVoice, narratorVoice, roleplayMode, state])

  const label = state === 'synthesising' ? 'Preparing...' : state === 'playing' ? 'Stop' : 'Read'
  const active = state !== 'idle'

  return (
    <button type="button" onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${active ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
      title={label}>
      {state === 'synthesising' ? (
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-gold/30 border-t-gold" />
      ) : state === 'playing' ? (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" /></svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
      )}
      {label}
    </button>
  )
}
