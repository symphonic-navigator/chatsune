import { audioPlayback } from '../infrastructure/audioPlayback'
import { setActiveReader } from '../components/ReadAloudButton'
import type { StreamingSentencer } from './streamingSentencer'
import type { NarratorMode, TTSEngine, VoicePreset } from '../types'

/**
 * Streaming auto-read session object shared between the chat view's
 * sentencer-driven producer and any external controllers (conversational mode)
 * that need to cancel playback as part of a barge.
 */
export interface StreamingAutoReadSession {
  tts: TTSEngine
  voice: VoicePreset
  narratorVoice: VoicePreset
  mode: NarratorMode
  gapMs: number
  messageId: string
  sentencer: StreamingSentencer
  lastTextLength: number
  chain: Promise<void>
  cancelled: boolean
}

// Module-level slot holding the active session. Kept here (not in ChatView
// local state) so other modules can call `cancelStreamingAutoRead` without
// importing React refs.
let activeSession: StreamingAutoReadSession | null = null

export function getActiveStreamingAutoRead(): StreamingAutoReadSession | null {
  return activeSession
}

export function setActiveStreamingAutoRead(session: StreamingAutoReadSession | null): void {
  activeSession = session
}

/**
 * Cancel the currently active streaming auto-read session.
 *
 * Effects:
 *   - Marks the session cancelled so any in-flight synthesis promises drop
 *     their results instead of enqueueing audio.
 *   - Stops all queued / playing audio via audioPlayback.
 *   - Clears the active-reader indicator used by <ReadAloudButton>.
 *
 * Idempotent — safe to call when no session is active.
 */
export function cancelStreamingAutoRead(): void {
  const session = activeSession
  if (!session) {
    audioPlayback.stopAll()
    setActiveReader(null, 'idle')
    return
  }
  session.cancelled = true
  activeSession = null
  setActiveReader(null, 'idle')
  audioPlayback.stopAll()
}
