import { useChatStore } from '../../core/store/chatStore'

interface Props {
  sessionId: string
  className?: string
}

/**
 * Subtle 6-px pulse-dot rendered next to a session row when that session
 * has an active inference streaming. Driven by chatStore.streamsBySession.
 *
 * Aesthetic: monochrome accent, gentle pulse — same restraint as inline
 * voice-tag pills. Not a status indicator with rich state; just "alive".
 */
export function StreamingIndicatorDot({ sessionId, className = '' }: Props) {
  const isStreaming = useChatStore((s) =>
    Boolean(s.streamsBySession.get(sessionId)?.isStreaming),
  )
  if (!isStreaming) return null
  return (
    <span
      role="status"
      aria-label="response streaming"
      className={
        'inline-block h-1.5 w-1.5 rounded-full bg-white/70 ' +
        'animate-pulse-soft ' +
        className
      }
    />
  )
}
