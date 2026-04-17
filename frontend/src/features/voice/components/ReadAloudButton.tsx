import { useCallback, useEffect, useState } from 'react'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { parseForSpeech } from '../pipeline/audioParser'
import { readAloudCacheKey } from '../pipeline/readAloudCacheKey'
import type { NarratorMode, SpeechSegment, VoicePreset } from '../types'
import { useSecretsStore } from '../../integrations/secretsStore'
import { useIntegrationsStore } from '../../integrations/store'
import type { PersonaDto } from '../../../core/types/persona'
import { useNotificationStore } from '../../../core/store/notificationStore'

interface ReadAloudButtonProps {
  messageId: string
  content: string
  persona?: PersonaDto | null
  dialogueVoice?: VoicePreset
  narratorVoice?: VoicePreset
  mode?: NarratorMode
}

type ReadState = 'idle' | 'synthesising' | 'playing'

// ── Global active-reader state ──
// Only one ReadAloudButton (or auto-read trigger) is active at a time.
// Both activeMessageId and activeState are kept together so buttons render
// the correct indicator regardless of which entry point drove them.

type Listener = () => void
let activeMessageId: string | null = null
let activeState: ReadState = 'idle'
const listeners = new Set<Listener>()

export function setActiveReader(id: string | null, state: ReadState): void {
  activeMessageId = id
  activeState = state
  listeners.forEach((fn) => fn())
}

function useActiveReader(messageId: string): { isActive: boolean; state: ReadState } {
  const [snapshot, setSnapshot] = useState(() => ({
    isActive: activeMessageId === messageId,
    state: activeState,
  }))
  useEffect(() => {
    const update = () => setSnapshot({ isActive: activeMessageId === messageId, state: activeState })
    listeners.add(update)
    update()
    return () => { listeners.delete(update) }
  }, [messageId])
  return snapshot
}

// ── LRU cache ──

interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

function cacheGet(key: string): CachedAudio | undefined {
  const entry = cache.get(key)
  if (entry) { cache.delete(key); cache.set(key, entry) }
  return entry
}

function cachePut(key: string, entry: CachedAudio): void {
  cache.delete(key)
  cache.set(key, entry)
  if (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
}

// ── Gap resolution ──

// Reads the playback_gap_ms value from a user's TTS integration config, which
// is stored as a plain object. Values may be persisted as either string (from
// the <select>) or number; both are accepted. Defaults to 100 ms when missing
// or malformed.
function resolveGapMs(integrationCfg: Record<string, unknown> | undefined): number {
  const raw = integrationCfg?.playback_gap_ms
  if (typeof raw === 'string') {
    const n = Number.parseInt(raw, 10)
    if (Number.isFinite(n) && n >= 0) return n
  }
  if (typeof raw === 'number' && Number.isFinite(raw) && raw >= 0) return raw
  return 500
}

// ── Shared synthesis runner ──

async function runReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
  gapMs: number,
): Promise<void> {
  const tts = ttsRegistry.active()
  if (!tts?.isReady()) { setActiveReader(null, 'idle'); return }

  const cacheKey = readAloudCacheKey(messageId, primary.id, narratorVoiceId, mode)

  audioPlayback.setCallbacks({
    gapMs,
    onSegmentStart: () => { if (activeMessageId === messageId) setActiveReader(messageId, 'playing') },
    onFinished: () => { if (activeMessageId === messageId) setActiveReader(null, 'idle') },
  })

  const cached = cacheGet(cacheKey)
  if (cached) {
    setActiveReader(messageId, 'playing')
    for (const { audio, segment } of cached.segments) {
      audioPlayback.enqueue(audio, segment)
    }
    audioPlayback.closeStream()
    return
  }

  const parsed = parseForSpeech(content, mode)
  if (parsed.length === 0) { setActiveReader(null, 'idle'); return }

  setActiveReader(messageId, 'synthesising')

  try {
    const results: CachedAudio['segments'] = []
    for (const segment of parsed) {
      if (activeMessageId !== messageId) return // cancelled
      const voice = segment.type === 'voice' ? primary : narrator
      const audio = await tts.synthesise(segment.text, voice)
      if (activeMessageId !== messageId) return
      results.push({ audio, segment })
      audioPlayback.enqueue(audio, segment)
    }
    cachePut(cacheKey, { segments: results })
    audioPlayback.closeStream()
  } catch (err) {
    if (activeMessageId !== messageId) return
    console.error('[ReadAloud] TTS synthesis failed:', err)
    setActiveReader(null, 'idle')
    const isAuthError = err instanceof Error && (err.message.includes('401') || err.message.includes('Unauthorized'))
    useNotificationStore.getState().addNotification({
      level: 'error',
      title: 'Read aloud failed',
      message: isAuthError
        ? "Couldn't read reply aloud — check your Mistral API key."
        : "Couldn't read reply aloud — check the console for details.",
    })
  }
}

// ── Imperative trigger for auto-read ──

/**
 * Trigger read-aloud for a message programmatically. Drives the same global
 * state and cache as the manual click path.
 */
export async function triggerReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
  gapMs: number,
): Promise<void> {
  audioPlayback.stopAll()
  setActiveReader(messageId, 'synthesising')
  await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, mode, gapMs)
}

// ── Component ──

export function ReadAloudButton({ messageId, content, persona, dialogueVoice, narratorVoice, mode }: ReadAloudButtonProps) {
  useSecretsStore((s) => s.secrets)
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const { isActive, state } = useActiveReader(messageId)

  const activeTTS = definitions.find(
    (d) => d.capabilities?.includes('tts_provider') && configs?.[d.id]?.enabled,
  )
  const ttsReady = ttsRegistry.active()?.isReady() === true
  const integrationCfg = activeTTS ? persona?.integration_configs?.[activeTTS.id] : undefined
  const voiceId = (integrationCfg?.voice_id as string | undefined) ?? undefined
  const narratorVoiceId = (integrationCfg?.narrator_voice_id as string | null | undefined) ?? null
  const resolvedMode: NarratorMode = mode ?? persona?.voice_config?.narrator_mode ?? 'off'
  const integrationUserConfig = activeTTS ? configs?.[activeTTS.id]?.config : undefined
  const gapMs = resolveGapMs(integrationUserConfig)

  const handleClick = useCallback(async () => {
    if (isActive && state !== 'idle') {
      audioPlayback.stopAll()
      setActiveReader(null, 'idle')
      return
    }

    audioPlayback.stopAll()

    const tts = ttsRegistry.active()
    if (!tts) {
      console.warn('[ReadAloud] No TTS engine active')
      return
    }

    const personaVoice = voiceId ? tts.voices.find((v) => v.id === voiceId) : undefined
    const primary = dialogueVoice ?? personaVoice
    if (!primary) {
      console.warn('[ReadAloud] No voice resolved')
      return
    }

    const personaNarrator = narratorVoiceId ? tts.voices.find((v) => v.id === narratorVoiceId) : undefined
    const narrator: VoicePreset = narratorVoice ?? personaNarrator ?? primary

    setActiveReader(messageId, 'synthesising')
    await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, resolvedMode, gapMs)
  }, [messageId, content, dialogueVoice, narratorVoice, resolvedMode, isActive, state, voiceId, narratorVoiceId, gapMs])

  if (!ttsReady || !voiceId) return null

  const displayState = isActive ? state : 'idle'
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
