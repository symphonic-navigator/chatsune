import { useCallback, useEffect, useRef, useState } from 'react'
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

// ── Global active-reader tracker ──
// Only one ReadAloudButton can be active at a time. When a new one starts,
// the previous one is cancelled. Each button subscribes to changes.

type Listener = () => void
let activeMessageId: string | null = null
const listeners = new Set<Listener>()

export function setActiveReader(id: string | null): void {
  activeMessageId = id
  listeners.forEach((fn) => fn())
}

function useActiveReader(messageId: string): boolean {
  const [active, setActive] = useState(activeMessageId === messageId)
  useEffect(() => {
    const check = () => setActive(activeMessageId === messageId)
    listeners.add(check)
    return () => { listeners.delete(check) }
  }, [messageId])
  return active
}

// ── LRU cache ──

interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

function cacheGet(id: string): CachedAudio | undefined {
  const entry = cache.get(id)
  if (entry) { cache.delete(id); cache.set(id, entry) }
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

// ── Component ──

export function ReadAloudButton({ messageId, content, dialogueVoice, narratorVoice, roleplayMode = false }: ReadAloudButtonProps) {
  const isActive = useActiveReader(messageId)
  const [localState, setLocalState] = useState<ReadState>('idle')
  const stateRef = useRef<ReadState>('idle')
  const genRef = useRef(0) // generation counter to cancel stale synthesis

  const setState = useCallback((s: ReadState) => {
    stateRef.current = s
    setLocalState(s)
  }, [])

  // If another button took over, reset our state
  useEffect(() => {
    if (!isActive && stateRef.current !== 'idle') {
      setState('idle')
    }
  }, [isActive, setState])

  const handleClick = useCallback(async () => {
    // If WE are active, stop
    if (isActive && stateRef.current !== 'idle') {
      audioPlayback.stopAll()
      setActiveReader(null)
      setState('idle')
      return
    }

    // Take over: stop any other active reader
    audioPlayback.stopAll()
    setActiveReader(messageId)
    const gen = ++genRef.current

    audioPlayback.setCallbacks({
      onSegmentStart: () => { if (gen === genRef.current) setState('playing') },
      onFinished: () => { if (gen === genRef.current) { setState('idle'); setActiveReader(null) } },
    })

    // Cache hit → instant playback
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
      setActiveReader(null)
      return
    }
    const fallbackVoice = tts.voices[0]
    const dVoice = dialogueVoice ?? fallbackVoice
    const nVoice = narratorVoice ?? fallbackVoice
    const parsed = parseForSpeech(content, roleplayMode)
    if (parsed.length === 0) { setActiveReader(null); return }

    setState('synthesising')

    try {
      const results: CachedAudio['segments'] = []
      for (const segment of parsed) {
        if (gen !== genRef.current) return // cancelled
        const voice = segment.type === 'voice' ? dVoice : nVoice
        const audio = await tts.synthesise(segment.text, voice)
        if (gen !== genRef.current) return // cancelled between segments
        results.push({ audio, segment })
        audioPlayback.enqueue(audio, segment)
      }
      cachePut(messageId, { segments: results })
    } catch (err) {
      if (gen !== genRef.current) return // cancelled, not a real error
      console.error('[ReadAloud] TTS synthesis failed:', err)
      setState('idle')
      setActiveReader(null)
    }
  }, [messageId, content, dialogueVoice, narratorVoice, roleplayMode, setState, isActive])

  const displayState = isActive ? localState : 'idle'
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
