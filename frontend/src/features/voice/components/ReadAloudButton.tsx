import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useCockpitStore } from '../../chat/cockpit/cockpitStore'
import { useOutletContext } from 'react-router-dom'
import { resolveTTSEngine, resolveTTSIntegrationId } from '../engines/resolver'
import { resolveGapMs } from '../engines/defaults'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { parseForSpeech } from '../pipeline/audioParser'
import { readAloudCacheKey } from '../pipeline/readAloudCacheKey'
import type { NarratorMode, SpeechSegment, VoicePreset } from '../types'
import { useSecretsStore } from '../../integrations/secretsStore'
import { useIntegrationsStore } from '../../integrations/store'
import { ResponseTagBuffer, type PendingEffect } from '../../integrations/responseTagProcessor'
import { emitInlineTrigger } from '../../integrations/inlineTriggerBus'
import type { PersonaDto } from '../../../core/types/persona'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { applyModulation, resolveModulation, type VoiceModulation } from '../pipeline/applyModulation'
import { providerSupportsExpressiveMarkup } from '../engines/expressiveMarkupCapability'

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

/**
 * Subscribes to the global read-aloud active state. Returns true while any
 * message is synthesising or playing via the read-aloud path (manual click
 * or auto-read). The cockpit voice button uses this to decide whether to
 * render the "stop playback" variant in normal chat mode, where playback
 * does not flow through the live voice pipeline.
 */
export function useIsReadingAloud(): boolean {
  const [active, setActive] = useState(() => activeMessageId !== null && activeState !== 'idle')
  useEffect(() => {
    const update = () => setActive(activeMessageId !== null && activeState !== 'idle')
    listeners.add(update)
    update()
    return () => { listeners.delete(update) }
  }, [])
  return active
}

/**
 * Stop any in-flight read-aloud: cancel audio playback and clear the global
 * active-reader state so every subscriber flips back to idle. Safe to call
 * when nothing is playing — it's a no-op in that case.
 */
export function stopActiveReadAloud(): void {
  audioPlayback.stopAll()
  setActiveReader(null, 'idle')
}

// ── LRU cache ──

interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

// Listeners called whenever the cache mutates (insert or evict). Used by
// ReadAloudButton instances so the green "cached" pill reacts to cache
// changes without turning the cache itself into a Zustand store.
const cacheListeners = new Set<() => void>()

function notifyCacheListeners(): void {
  for (const listener of cacheListeners) listener()
}

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
  notifyCacheListeners()
}

// React hook: returns a number that increments on every cache mutation.
// Components depend on this in useMemo deps to re-evaluate cache-hit
// derivations when the cache changes.
function useCacheTick(): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const listener = () => setTick((t) => t + 1)
    cacheListeners.add(listener)
    return () => {
      cacheListeners.delete(listener)
    }
  }, [])
  return tick
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
  modulation: VoiceModulation,
  persona: PersonaDto | null | undefined,
  supportsExpressive: boolean,
): Promise<void> {
  const tts = resolveTTSEngine(persona)
  if (!tts?.isReady()) { setActiveReader(null, 'idle'); return }

  const cacheKey = readAloudCacheKey(messageId, primary.id, narratorVoiceId, mode)

  audioPlayback.setCallbacks({
    gapMs,
    onSegmentStart: () => { if (activeMessageId === messageId) setActiveReader(messageId, 'playing') },
    onFinished: () => { if (activeMessageId === messageId) setActiveReader(null, 'idle') },
    // Re-emit any segment-bound inline triggers parked by the pre-pass below.
    // The trigger fires in lockstep with TTS playback start, mirroring the
    // live-stream path. `event.source` is already stamped 'read_aloud' by
    // audioPlayback from the queue entry's source field.
    onInlineTrigger: (event) => emitInlineTrigger(event, `read-aloud-${messageId}`),
  })

  const cached = cacheGet(cacheKey)
  if (cached) {
    // Cache hit: cached segments already carry their `effects` from the
    // original parseForSpeech run, so audioPlayback's onInlineTrigger
    // callback (wired above) will re-fire them in lockstep with playback.
    // We must NOT run the buffer pre-pass here — process() would allocate
    // fresh effectIds, re-run every plugin's sideEffect (e.g. Lovense
    // hardware calls) and then flush() would emit a second set of inline
    // triggers on the bus, in addition to the segment-bound replay below.
    setActiveReader(messageId, 'playing')
    for (const { audio, segment } of cached.segments) {
      audioPlayback.enqueue(audio, applyModulation(segment, modulation), undefined, 'read_aloud')
    }
    audioPlayback.closeStream()
    return
  }

  // Cache miss: pipe the content through a fresh ResponseTagBuffer so the
  // same tag-detection / placeholder logic that the live stream uses also
  // runs here. The map is shared with parseForSpeech below: sentence-bound
  // tags get parked, claimed by the matching SpeechSegment, and fired at
  // segment-start; tags outside any speakable segment fall through to the
  // immediate-emit path via emitInlineTrigger when buffer.flush() runs.
  //
  // Note the ordering: process(...) parks tags, parseForSpeech below claims
  // them off the shared map, then flush() emits any orphan that parser did
  // not claim. Calling flush() before parseForSpeech would drain the map
  // first and defeat sentence-sync.
  const pending = new Map<string, PendingEffect>()
  const buffer = new ResponseTagBuffer(
    () => {}, // onTagResolved no-op: read-aloud renders from already-rendered HTML, not stream tokens.
    'read_aloud',
    pending,
    (trigger) => emitInlineTrigger(trigger, `read-aloud-${messageId}`),
  )
  const sanitisedContent = buffer.process(content)
  const parsed = parseForSpeech(sanitisedContent, mode, supportsExpressive, pending, 'read_aloud')
  // Drain any pending entries that parseForSpeech did not claim (text was
  // stripped before reaching a speakable segment, or no speakable segment
  // existed at all). Also returns any unterminated-tag remainder, which
  // is irrelevant for read-aloud (full message in, no truncation).
  buffer.flush()
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
      audioPlayback.enqueue(audio, applyModulation(segment, modulation), undefined, 'read_aloud')
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
  modulation: VoiceModulation,
  persona?: PersonaDto | null,
  supportsExpressive: boolean = false,
): Promise<void> {
  audioPlayback.stopAll()
  setActiveReader(messageId, 'synthesising')
  await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, mode, gapMs, modulation, persona, supportsExpressive)
}

// ── Component ──

export function ReadAloudButton({ messageId, content, persona, dialogueVoice, narratorVoice, mode }: ReadAloudButtonProps) {
  useSecretsStore((s) => s.secrets)
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const { isActive, state } = useActiveReader(messageId)

  // Resolve the active TTS integration the same way the engine is resolved —
  // honour persona.voice_config.tts_provider_id first, then fall back. If we
  // looked up "first enabled" here instead, persona.integration_configs for
  // xAI would be read from Mistral's config dict and voice_id would come
  // back undefined even though a voice is configured.
  const ttsIntegrationId = resolveTTSIntegrationId(persona)
  const activeTTS = ttsIntegrationId
    ? definitions.find((d) => d.id === ttsIntegrationId)
    : undefined
  const ttsReady = resolveTTSEngine(persona)?.isReady() === true
  const integrationCfg = activeTTS ? persona?.integration_configs?.[activeTTS.id] : undefined
  const voiceId = (integrationCfg?.voice_id as string | undefined) ?? undefined
  const narratorVoiceId = (integrationCfg?.narrator_voice_id as string | null | undefined) ?? null
  const resolvedMode: NarratorMode = mode ?? persona?.voice_config?.narrator_mode ?? 'off'
  const integrationUserConfig = activeTTS ? configs?.[activeTTS.id]?.config : undefined
  const gapMs = resolveGapMs(activeTTS?.id, integrationUserConfig)

  const cacheTick = useCacheTick()
  const isCached = useMemo(() => {
    if (!voiceId) return false
    const key = readAloudCacheKey(messageId, voiceId, narratorVoiceId, resolvedMode)
    return cacheGet(key) !== undefined
    // cacheTick triggers re-evaluation when the cache mutates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messageId, voiceId, narratorVoiceId, resolvedMode, cacheTick])

  const outlet = useOutletContext<{
    openPersonaOverlay: (personaId: string | null, tab?: string) => void
  }>()

  const personaId = persona?.id ?? null

  const handleClick = useCallback(async () => {
    if (isActive && state !== 'idle') {
      audioPlayback.stopAll()
      setActiveReader(null, 'idle')
      return
    }

    audioPlayback.stopAll()

    const tts = resolveTTSEngine(persona)
    if (!tts) {
      console.warn('[ReadAloud] No TTS engine available')
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

    const modulation = resolveModulation(persona?.voice_config)
    const supportsExpressive = providerSupportsExpressiveMarkup(ttsIntegrationId, definitions)

    setActiveReader(messageId, 'synthesising')
    await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, resolvedMode, gapMs, modulation, persona, supportsExpressive)
  }, [messageId, content, dialogueVoice, narratorVoice, resolvedMode, isActive, state, voiceId, narratorVoiceId, gapMs, persona, ttsIntegrationId, definitions])

  // Auto-read request channel. AssistantMessage detects the streaming→done
  // transition (the ReadAloudButton itself only mounts after streaming ends,
  // so it cannot observe the transition locally) and writes our messageId
  // into cockpitStore.pendingAutoReadMessageId. We consume it here.
  const pendingAutoReadId = useCockpitStore((s) => s.pendingAutoReadMessageId)
  const clearAutoReadRequest = useCockpitStore((s) => s.clearAutoReadRequest)
  // Ref guard against React.StrictMode's intentional double-invoke of effects
  // in dev: without it the mount → cleanup → mount simulation fires handleClick
  // twice because the captured snapshot of pendingAutoReadId stays the same
  // across the two setups (clearAutoReadRequest runs between them, but the
  // local variable does not update without a new render).
  const firedForMessageRef = useRef<string | null>(null)
  useEffect(() => {
    if (pendingAutoReadId !== messageId) return
    if (firedForMessageRef.current === messageId) return
    if (!ttsReady || !voiceId) return
    if (isActive) return
    firedForMessageRef.current = messageId
    clearAutoReadRequest()
    void handleClick()
  }, [pendingAutoReadId, messageId, ttsReady, voiceId, isActive, handleClick, clearAutoReadRequest])

  if (!ttsReady || !voiceId) {
    if (!personaId) return null
    return (
      <button
        type="button"
        onClick={() => outlet.openPersonaOverlay(personaId, 'voice')}
        title="Configure voice"
        aria-label="Configure voice"
        className="flex items-center gap-1 text-[11px] text-white/20 transition-colors hover:text-white/45"
      >
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
        Configure voice
      </button>
    )
  }

  const displayState = isActive ? state : 'idle'
  const label = displayState === 'synthesising' ? 'Preparing...' : displayState === 'playing' ? 'Stop' : 'Read'
  const active = displayState !== 'idle'

  return (
    <button type="button" onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${active ? 'text-gold' : isCached ? 'text-emerald-400/45 hover:text-emerald-400/65' : 'text-white/25 hover:text-white/50'}`}
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
