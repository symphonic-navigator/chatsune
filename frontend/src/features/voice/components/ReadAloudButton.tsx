import { useCallback, useRef, useState } from 'react'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { parseForSpeech } from '../pipeline/audioParser'
import type { SpeechSegment, VoicePreset } from '../types'

interface ReadAloudButtonProps {
  messageId: string
  content: string
  dialogueVoice?: VoicePreset
  narratorVoice?: VoicePreset
  roleplayMode?: boolean
}

type ReadState = 'idle' | 'synthesising' | 'playing'

/** LRU cache of synthesised audio keyed by message ID. */
interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

function cacheGet(id: string): CachedAudio | undefined {
  const entry = cache.get(id)
  if (entry) {
    cache.delete(id)
    cache.set(id, entry)
  }
  return entry
}

function cachePut(id: string, entry: CachedAudio): void {
  cache.delete(id)
  cache.set(id, entry)
  if (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
}

export function ReadAloudButton({ messageId, content, dialogueVoice, narratorVoice, roleplayMode = false }: ReadAloudButtonProps) {
  const [displayState, setDisplayState] = useState<ReadState>('idle')
  // Ref mirrors displayState to avoid stale closures in async callbacks
  const stateRef = useRef<ReadState>('idle')

  const setState = useCallback((s: ReadState) => {
    stateRef.current = s
    setDisplayState(s)
  }, [])

  const handleClick = useCallback(async () => {
    const current = stateRef.current
    if (current === 'playing' || current === 'synthesising') {
      audioPlayback.stopAll()
      setState('idle')
      return
    }

    // Clean any stale playback state
    audioPlayback.stopAll()

    audioPlayback.setCallbacks({
      onSegmentStart: () => setState('playing'),
      onFinished: () => setState('idle'),
    })

    // Check cache first
    const cached = cacheGet(messageId)
    if (cached) {
      setState('playing')
      for (const { audio, segment } of cached.segments) {
        audioPlayback.enqueue(audio, segment)
      }
      return
    }

    // Synthesise fresh
    const tts = ttsRegistry.active()
    if (!tts) {
      console.warn('[ReadAloud] No TTS engine active — complete voice setup first')
      return
    }
    const fallbackVoice = tts.voices[0]
    const dVoice = dialogueVoice ?? fallbackVoice
    const nVoice = narratorVoice ?? fallbackVoice
    const parsed = parseForSpeech(content, roleplayMode)
    if (parsed.length === 0) return

    setState('synthesising')

    // Yield to browser so React can paint the spinner before
    // TTS synthesis blocks the main thread
    await new Promise((r) => requestAnimationFrame(r))

    try {
      const results: CachedAudio['segments'] = []
      for (const segment of parsed) {
        const voice = segment.type === 'voice' ? dVoice : nVoice
        const audio = await tts.synthesise(segment.text, voice)
        results.push({ audio, segment })
        audioPlayback.enqueue(audio, segment)
        // Yield between segments so the UI stays responsive
        await new Promise((r) => requestAnimationFrame(r))
      }
      cachePut(messageId, { segments: results })
    } catch (err) {
      console.error('[ReadAloud] TTS synthesis failed:', err)
      setState('idle')
    }
  }, [messageId, content, dialogueVoice, narratorVoice, roleplayMode, setState])

  const label = displayState === 'synthesising' ? 'Preparing...' : displayState === 'playing' ? 'Stop' : 'Read'
  const active = displayState !== 'idle'

  return (
    <button type="button" onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${active ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
      title={label}>
      {displayState === 'synthesising' ? (
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-gold/30 border-t-gold" />
      ) : displayState === 'playing' ? (
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
