import { useSecretsStore } from '../../integrations/secretsStore'
import { resolveSTTEngine } from '../engines/resolver'
import type { PipelinePhase } from '../types'

interface VoiceButtonProps {
  phase: PipelinePhase
  hasText: boolean
  isStreaming: boolean
  disabled: boolean
  hasPendingUploads: boolean
  volumeLevel: number
  onSend: () => void
  onCancel: () => void
  onMicPress: () => void
  onMicRelease: () => void
  onStopRecording: () => void
}

export function VoiceButton({
  phase,
  hasText,
  isStreaming,
  disabled,
  hasPendingUploads,
  volumeLevel,
  onSend,
  onCancel,
  onMicPress,
  onMicRelease,
  onStopRecording,
}: VoiceButtonProps) {
  // Re-render whenever secrets change so the mic gate reflects current STT readiness.
  useSecretsStore((s) => s.secrets)
  const sttReady = resolveSTTEngine()?.isReady() === true

  const baseClass = 'flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg transition-colors'

  // State 1: Streaming — cancel button (red stop)
  if (isStreaming) {
    return (
      <button
        type="button"
        data-testid="cancel-button"
        onClick={onCancel}
        title="Cancel response"
        aria-label="Cancel response"
        className={`${baseClass} border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20`}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // State 2: Recording — stop recording button (red with volume glow)
  if (phase === 'recording') {
    return (
      <button
        type="button"
        onClick={onStopRecording}
        title="Stop recording"
        aria-label="Stop recording"
        className={`${baseClass} border border-red-500/40 text-red-400`}
        style={{ background: `rgba(239, 68, 68, ${0.1 + volumeLevel * 0.3})` }}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // State 3: Transcribing — spinner (disabled)
  if (phase === 'transcribing') {
    return (
      <button
        type="button"
        disabled
        title="Transcribing..."
        aria-label="Transcribing"
        className={`${baseClass} border border-white/10 bg-white/6 text-white/40 opacity-70`}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          className="animate-spin"
        >
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" strokeDasharray="28" strokeDashoffset="10" strokeLinecap="round" />
        </svg>
      </button>
    )
  }

  // State 4: Speaking — stop playback button (gold)
  if (phase === 'speaking') {
    return (
      <button
        type="button"
        onClick={onStopRecording}
        title="Stop playback"
        aria-label="Stop playback"
        className={`${baseClass} border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/20`}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // State 5: Has text, OR STT not ready (empty prompt but no mic available) — send button
  if (hasText || !sttReady) {
    return (
      <button
        type="button"
        data-testid="send-button"
        onClick={onSend}
        disabled={!hasText || disabled || hasPendingUploads}
        title="Send message"
        aria-label="Send message"
        className={`${baseClass} border border-white/10 bg-white/6 text-white/60 hover:bg-white/10 hover:text-white/85 disabled:opacity-30 disabled:hover:bg-white/6`}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M2 14L14.5 8L2 2V6.5L10 8L2 9.5V14Z" fill="currentColor" />
        </svg>
      </button>
    )
  }

  // State 6: Empty prompt and STT is ready — mic button (hold to record)
  return (
    <button
      type="button"
      disabled={disabled}
      title="Hold to record"
      aria-label="Hold to record"
      onMouseDown={onMicPress}
      onMouseUp={onMicRelease}
      onTouchStart={onMicPress}
      onTouchEnd={onMicRelease}
      className={`${baseClass} border border-white/10 bg-white/6 text-white/60 hover:bg-white/10 hover:text-white/85 disabled:opacity-30`}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <rect x="5.5" y="1.5" width="5" height="8" rx="2.5" stroke="currentColor" strokeWidth="1.2" />
        <path d="M3 7.5C3 10.26 5.24 12.5 8 12.5C10.76 12.5 13 10.26 13 7.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        <line x1="8" y1="12.5" x2="8" y2="14.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        <line x1="6" y1="14.5" x2="10" y2="14.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
    </button>
  )
}
