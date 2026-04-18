import type { ConversationPhase } from '../stores/conversationModeStore'

interface ConversationModeButtonProps {
  active: boolean
  available: boolean
  phase: ConversationPhase
  onToggle: () => void
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
 *   - greyed out when STT or TTS is not available
 *   - prominent accent colour when inactive-but-available
 *   - pulsing live indicator + phase dot when active
 */
export function ConversationModeButton({ active, available, phase, onToggle }: ConversationModeButtonProps) {
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

function ConvIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="6" y="2" width="4" height="7" rx="2" />
      <path d="M3.5 7.5C3.5 10 5.5 11.5 8 11.5C10.5 11.5 12.5 10 12.5 7.5" />
      <line x1="8" y1="11.5" x2="8" y2="13.5" />
      <path d="M1.5 5.5C1.5 5.5 1 7 1 8C1 9 1.5 10.5 1.5 10.5" />
      <path d="M14.5 5.5C14.5 5.5 15 7 15 8C15 9 14.5 10.5 14.5 10.5" />
    </svg>
  )
}
