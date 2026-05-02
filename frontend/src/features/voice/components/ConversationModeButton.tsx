import { useEffect } from 'react'
import type { ConversationPhase } from '../stores/conversationModeStore'
import { useProvidersStore } from '../../../core/store/providersStore'
import type { VoiceLifecycle } from '@/features/voice-commands'
import { firstEnabledIntegrationId, TTS_CAP } from '../engines/resolver'
import { useIntegrationsStore } from '../../integrations/store'

/** Maps a voice integration id onto the Premium Provider Account that owns
 *  its API key. Integrations not in this map are either unlinked (their key
 *  lives in the per-integration config) or premium-account-agnostic. */
const PROVIDER_ID_BY_INTEGRATION: Record<string, string> = {
  xai_voice: 'xai',
  mistral_voice: 'mistral',
}

function providerIdForIntegration(integrationId: string | null | undefined): string | null {
  if (!integrationId) return null
  return PROVIDER_ID_BY_INTEGRATION[integrationId] ?? null
}

/** Loosely-typed persona prop — we only inspect a handful of voice-related
 *  fields and both real `PersonaDto` and test doubles satisfy this.
 *
 *  IMPORTANT: `tts_provider_id` is nested under `voice_config` in the data
 *  model (see `shared/dtos/persona.py` `VoiceConfigDto.tts_provider_id`).
 *  Earlier iterations of this file read the field top-level on the persona
 *  which always resolved to `undefined`, causing the button to be
 *  permanently strikethrough even when a premium account was configured. */
interface PersonaVoiceShape {
  id?: string
  voice_config?: {
    tts_provider_id?: string | null
  } | null
}

/**
 * True when the persona's effective TTS integration has a configured
 * Premium Provider Account. The effective integration is the persona's
 * explicit `voice_config.tts_provider_id` if set, otherwise the first
 * enabled TTS integration (mirroring the cockpit Live-button gate via
 * resolveTTSIntegrationId in voice/engines/resolver.ts).
 */
function useVoiceAvailable(persona: PersonaVoiceShape | null | undefined): boolean {
  // Select the stable `accounts` array rather than the derived Set — the
  // latter is a new object every render and causes a re-render loop.
  const accounts = useProvidersStore((s) => s.accounts)
  const hydrated = useProvidersStore((s) => s.hydrated)
  const loading = useProvidersStore((s) => s.loading)
  const error = useProvidersStore((s) => s.error)
  const refresh = useProvidersStore((s) => s.refresh)
  // Subscribe to the integrations store so a toggle of mistral_voice /
  // xai_voice immediately re-renders this component. firstEnabledIntegrationId
  // reads from the same store via getState() but reading via a selector here
  // is what wires the React subscription.
  useIntegrationsStore((s) => s.definitions)
  useIntegrationsStore((s) => s.configs)

  // Lazy hydrate: if no consumer has loaded the providers store yet (e.g.
  // the user hasn't opened the User-Modal since the app booted), the button
  // would otherwise show as unavailable until the modal is opened. Trigger
  // a one-off refresh on first mount; the `hydrated` flag prevents retries
  // when the account list is genuinely empty.
  useEffect(() => {
    if (!hydrated && !loading && error === null) void refresh()
  }, [hydrated, loading, error, refresh])

  // Mirror the cockpit Live-button gate: the persona's explicit
  // tts_provider_id wins, but if it is null/undefined we fall back to the
  // first enabled TTS integration, exactly like resolveTTSIntegrationId does
  // (see voice/engines/resolver.ts). This keeps the two gates from diverging.
  const explicitTtsId = persona?.voice_config?.tts_provider_id ?? undefined
  const effectiveTtsId = explicitTtsId ?? firstEnabledIntegrationId(TTS_CAP)
  if (!effectiveTtsId) return false

  const ttsPremium = providerIdForIntegration(effectiveTtsId)
  // If the resolved TTS integration is not premium-linked (e.g. a local
  // engine), we treat it as available — the legacy `available` prop path
  // still gates further downstream.
  if (!ttsPremium) return true
  const configuredIds = new Set(accounts.map((a) => a.provider_id))
  if (!configuredIds.has(ttsPremium)) return false
  // NOTE: no STT gate here. STT is a user-level setting living in
  // `useVoiceSettingsStore` (see `stt_provider_id` there), not a
  // persona-level field. Mixing the two concerns here was the cause of
  // the original drift; the user-level STT readiness check lives in the
  // voice engines resolver.
  return true
}

interface ConversationModeButtonProps {
  active?: boolean
  available?: boolean
  phase?: ConversationPhase
  onToggle?: () => void
  /** Persona to evaluate for voice availability. When supplied, the button
   *  checks whether the persona's voice integrations are backed by a
   *  configured Premium Provider Account. */
  persona?: PersonaVoiceShape | null
  /** Invoked when the button is clicked while voice is unavailable — should
   *  navigate the user to the persona voice-config flow. */
  onConfigure?: () => void
  /** Current voice-lifecycle state. When 'paused', click invokes `onResume`. */
  lifecycle?: VoiceLifecycle
  /** Invoked when the button is clicked while `lifecycle === 'paused'`. */
  onResume?: () => void
}

const PHASE_LABEL: Record<ConversationPhase, string> = {
  idle: 'Start conversational mode',
  listening: 'Listening...',
  'user-speaking': 'Hearing you',
  held: 'Holding the mic open',
  transcribing: 'Transcribing...',
  thinking: 'Thinking...',
  speaking: 'Speaking...',
}

const PHASE_DOT: Record<ConversationPhase, string> = {
  idle: 'bg-white/30',
  listening: 'bg-green-400 animate-pulse',
  'user-speaking': 'bg-red-400 animate-pulse',
  held: 'bg-gold',
  transcribing: 'bg-blue-400 animate-pulse',
  thinking: 'bg-purple-400 animate-pulse',
  speaking: 'bg-yellow-400 animate-pulse',
}

/**
 * Top-bar toggle for conversational mode.
 *
 *   - strikethrough + click-to-configure when the persona's voice integration
 *     is not backed by a Premium Provider Account
 *   - greyed out when STT or TTS is not available
 *   - prominent accent colour when inactive-but-available
 *   - pulsing live indicator + phase dot when active
 */
export function ConversationModeButton({
  active = false,
  available = true,
  phase = 'idle',
  onToggle,
  persona,
  onConfigure,
  lifecycle,
  onResume,
}: ConversationModeButtonProps) {
  const voiceAvailable = useVoiceAvailable(persona)

  // Persona-driven predicate wins when a persona is supplied: the user has
  // picked a voice integration whose premium account is missing, so point
  // them at the voice-config flow rather than silently disabling the button.
  if (persona && !voiceAvailable) {
    return (
      <button
        type="button"
        onClick={onConfigure}
        style={{ opacity: 0.4, textDecoration: 'line-through' }}
        className="flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/60 hover:bg-white/10"
        title="Voice provider not configured — click to configure"
        aria-label="Voice provider not configured — click to configure"
      >
        <ConvIcon />
        <span className="hidden sm:inline">Voice chat</span>
      </button>
    )
  }

  if (!available) {
    return (
      <button
        type="button"
        disabled
        className="flex items-center gap-1.5 rounded-full border border-white/8 bg-white/3 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/25"
        title="Configure a voice and transcription integration to enable conversational mode"
        aria-label="Conversational mode unavailable"
      >
        <ConvIcon />
        <span className="hidden sm:inline">Voice chat</span>
      </button>
    )
  }

  const baseClass =
    'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider transition-all'

  // Paused lifecycle preempts the gold "Live" path: amber pulsing pill with
  // a strikethrough mic. Clicking the pill resumes voice rather than toggling
  // conversation mode off, so a user who paused via wake-word ("hatsune
  // pause") can re-enter the listening loop with one tap.
  if (active && lifecycle === 'paused') {
    return (
      <button
        type="button"
        onClick={onResume}
        className={`${baseClass} border-amber-400/55 bg-amber-400/15 text-amber-400 animate-pulse shadow-[0_0_16px_rgba(251,191,36,0.35)]`}
        title="Voice paused — click to resume"
        aria-label="Resume voice"
        aria-pressed="true"
      >
        <ConvIcon muted />
        <span className="hidden sm:inline">Paused</span>
      </button>
    )
  }

  if (active) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className={`${baseClass} border-gold/50 bg-gold/15 text-gold shadow-[0_0_12px_rgba(249,226,175,0.25)] animate-pulse-slow`}
        title={`Stop conversational mode — ${PHASE_LABEL[phase]}`}
        aria-label="Stop conversational mode"
        aria-pressed="true"
      >
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${PHASE_DOT[phase]}`} />
        <ConvIcon />
        <span className="hidden sm:inline">Live</span>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      className={`${baseClass} border-gold/35 bg-gold/8 text-gold/90 hover:bg-gold/15 hover:border-gold/50`}
      title="Start conversational mode"
      aria-label="Start conversational mode"
      aria-pressed="false"
    >
      <ConvIcon />
      <span className="hidden sm:inline">Voice chat</span>
    </button>
  )
}

function ConvIcon({ muted }: { muted?: boolean } = {}) {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="6" y="2" width="4" height="7" rx="2" />
      <path d="M3.5 7.5C3.5 10 5.5 11.5 8 11.5C10.5 11.5 12.5 10 12.5 7.5" />
      <line x1="8" y1="11.5" x2="8" y2="13.5" />
      <path d="M1.5 5.5C1.5 5.5 1 7 1 8C1 9 1.5 10.5 1.5 10.5" />
      <path d="M14.5 5.5C14.5 5.5 15 7 15 8C15 9 14.5 10.5 14.5 10.5" />
      {muted && <path d="M2 2 14 14" strokeWidth="1.4" />}
    </svg>
  )
}
