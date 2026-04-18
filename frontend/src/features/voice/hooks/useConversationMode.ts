import { useCallback, useEffect, useRef } from 'react'
import { useConversationModeStore } from '../stores/conversationModeStore'
import { voicePipeline } from '../pipeline/voicePipeline'
import { audioCapture } from '../infrastructure/audioCapture'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { cancelStreamingAutoRead } from '../pipeline/streamingAutoReadControl'
import { useChatStore } from '../../../core/store/chatStore'
import { chatApi } from '../../../core/api/chat'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { setActiveReader } from '../components/ReadAloudButton'
import { sttRegistry } from '../engines/registry'

interface UseConversationModeOptions {
  /**
   * The current session id. Conversation-mode is per-session; switching
   * sessions tears conv-mode down. May be null between sessions.
   */
  sessionId: string | null
  /**
   * True iff the persona + active integrations can both transcribe AND
   * read aloud. The hook refuses to `enter()` when this is false and
   * auto-exits if it transitions to false mid-session.
   */
  available: boolean
  /**
   * Called when the controller has a transcribed utterance ready to send.
   * Use the same path a normal text send uses — the backend's
   * `cancel_all_for_user` cascade will abort any in-flight inference.
   */
  onSend: (text: string) => void
}

/**
 * Controller for conversational voice mode.
 *
 * Owns the transitions between listening / user-speaking / thinking /
 * speaking. Snapshots and restores the session reasoning override and the
 * persona auto_read flag so the user's chosen settings survive the
 * conversation. Reuses the existing streaming TTS pipeline by ensuring
 * auto_read is true while active; the sentencer/synth plumbing lives in
 * ChatView.
 *
 * The hook registers capture-level callbacks directly against
 * `audioCapture.startContinuous` (bypassing `voicePipeline.startRecording`)
 * so it can implement the hold-to-keep-talking gate without touching the
 * generic push-to-talk pipeline.
 */
export function useConversationMode({ sessionId, available, onSend }: UseConversationModeOptions): void {
  const active = useConversationModeStore((s) => s.active)
  const phase = useConversationModeStore((s) => s.phase)
  const isHolding = useConversationModeStore((s) => s.isHolding)
  const setPhase = useConversationModeStore((s) => s.setPhase)
  const exitStore = useConversationModeStore((s) => s.exit)
  const setPreviousReasoning = useConversationModeStore((s) => s.setPreviousReasoning)

  // Mirror isHolding into a ref so capture callbacks (which are created once
  // per listen-session) can read the current value without re-binding.
  const holdingRef = useRef(false)
  useEffect(() => { holdingRef.current = isHolding }, [isHolding])

  // Buffered audio produced by VAD speech-end events that were swallowed
  // because the user was holding the "keep talking" button. When the user
  // releases the hold (or a later speech-end arrives while NOT held), we
  // concatenate these with the final chunk and dispatch the whole thing to
  // STT as one utterance.
  const heldAudioRef = useRef<Float32Array[]>([])

  const isStreaming = useChatStore((s) => s.isStreaming)
  const isWaitingForResponse = useChatStore((s) => s.isWaitingForResponse)

  const phaseRef = useRef(phase)
  useEffect(() => { phaseRef.current = phase }, [phase])

  const activeRef = useRef(active)
  useEffect(() => { activeRef.current = active }, [active])

  const onSendRef = useRef(onSend)
  useEffect(() => { onSendRef.current = onSend }, [onSend])

  const sessionIdRef = useRef(sessionId)
  useEffect(() => { sessionIdRef.current = sessionId }, [sessionId])

  // Concatenate held+current chunks into a single Float32Array for STT.
  const flushHeldAudio = useCallback((finalChunk: Float32Array | null): Float32Array => {
    const heldChunks = heldAudioRef.current
    heldAudioRef.current = []
    const chunks: Float32Array[] = [...heldChunks]
    if (finalChunk && finalChunk.length > 0) chunks.push(finalChunk)
    const total = chunks.reduce((sum, c) => sum + c.length, 0)
    const merged = new Float32Array(total)
    let offset = 0
    for (const c of chunks) { merged.set(c, offset); offset += c.length }
    return merged
  }, [])

  // Run STT against an already-captured Float32Array and fire onSend on
  // any non-empty transcription. Called when the user's utterance ends
  // (release or normal VAD speech-end while not holding).
  const transcribeAndSend = useCallback(async (audio: Float32Array): Promise<void> => {
    if (!activeRef.current) return
    if (audio.length === 0) {
      setPhase('listening')
      return
    }
    setPhase('transcribing')
    const stt = sttRegistry.active()
    if (!stt) {
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Conversational mode stopped',
        message: 'No transcription engine is available.',
      })
      exitStore()
      return
    }
    try {
      const result = await stt.transcribe(audio)
      if (!activeRef.current) return
      const text = result.text.trim()
      if (!text) {
        setPhase('listening')
        return
      }
      // Defensive: flip phase to "thinking" immediately so the UI reflects
      // the handoff. The store-observer effect below will keep it in sync
      // as the actual stream starts.
      setPhase('thinking')
      onSendRef.current(text)
    } catch (err) {
      console.error('[ConversationMode] Transcription failed:', err)
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Transcription failed',
        message: "Couldn't transcribe audio — check the console for details.",
      })
      if (activeRef.current) setPhase('listening')
    }
  }, [setPhase, exitStore])

  // Silero fires onSpeechStart on any loud-enough frame — including brief
  // non-speech noise (chair creaks, keyboard clicks) that later turns out to
  // be a misfire. Reacting immediately would cut off playback for those
  // bursts. Instead we defer the barge by BARGE_DELAY_MS; if a misfire
  // arrives inside that window, the pending barge is cancelled and playback
  // continues untouched. Real speech typically lasts longer than this, so
  // the barge still fires for genuine interruptions with only a small delay.
  const BARGE_DELAY_MS = 150
  const pendingBargeRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPendingBarge = useCallback(() => {
    if (pendingBargeRef.current) {
      clearTimeout(pendingBargeRef.current)
      pendingBargeRef.current = null
    }
  }, [])

  const executeBarge = useCallback(() => {
    pendingBargeRef.current = null
    const current = phaseRef.current
    if (current === 'thinking' || current === 'speaking') {
      cancelStreamingAutoRead()
      audioPlayback.stopAll()
      setActiveReader(null, 'idle')
    }
    setPhase('user-speaking')
  }, [setPhase])

  /**
   * VAD speech-start handler. If the user speaks while the LLM is thinking
   * or a reply is playing, this is a BARGE: stop playback, drop any
   * in-flight TTS synthesis, and switch to "user-speaking". The server-side
   * cancel happens automatically once the new utterance is sent (the chat
   * handler invokes `cancel_all_for_user`). We defer by BARGE_DELAY_MS so
   * noise bursts that Silero later retracts via onVADMisfire don't cut
   * playback off.
   */
  const handleSpeechStart = useCallback(() => {
    if (!activeRef.current) return
    clearPendingBarge()
    pendingBargeRef.current = setTimeout(executeBarge, BARGE_DELAY_MS)
  }, [executeBarge, clearPendingBarge])

  /**
   * VAD speech-end handler. Two cases:
   *   (a) user is holding — we buffer the audio and stay in "user-speaking"
   *       so the UI keeps showing the hold button. Next speech-start is
   *       treated as a continuation of the same utterance.
   *   (b) user is NOT holding — concatenate any previously-held chunks with
   *       the final chunk and ship it off to STT.
   *
   * If a deferred barge is still pending (short but real speech that ended
   * inside the delay window), fire it now before handling the utterance so
   * playback stops before we transition to "transcribing".
   */
  const handleSpeechEnd = useCallback((audio: Float32Array) => {
    if (!activeRef.current) return
    if (pendingBargeRef.current) {
      clearPendingBarge()
      executeBarge()
    }
    if (holdingRef.current) {
      if (audio.length > 0) heldAudioRef.current.push(audio)
      // Stay in user-speaking; VAD will re-fire speech-start on the next
      // utterance and we'll continue accumulating.
      return
    }
    const merged = flushHeldAudio(audio)
    void transcribeAndSend(merged)
  }, [flushHeldAudio, transcribeAndSend, clearPendingBarge, executeBarge])

  /**
   * VAD misfire handler. Silero optimistically emits speech-start on any
   * loud-enough frame, then aborts via onVADMisfire (without ever firing
   * speech-end) if the burst was too short to qualify as speech. If the
   * deferred barge is still pending, drop it — the noise burst never
   * became real speech. Otherwise fall back to the listening phase so the
   * "Hold to keep talking" overlay doesn't linger. If the user is actively
   * holding, keep the overlay visible — a misfire during hold is just
   * noise between utterances.
   */
  const handleMisfire = useCallback(() => {
    if (pendingBargeRef.current) {
      clearPendingBarge()
      return
    }
    if (!activeRef.current) return
    if (holdingRef.current) return
    setPhase('listening')
  }, [setPhase, clearPendingBarge])

  /**
   * Teardown — stop VAD, stop playback, restore session settings. Safe to
   * call unconditionally; `exit()` on the store short-circuits if we're
   * already idle.
   */
  const teardown = useCallback(async (restoreSid: string | null) => {
    try { audioCapture.stopContinuous() } catch { /* not active */ }
    clearPendingBarge()
    cancelStreamingAutoRead()
    audioPlayback.stopAll()

    // Restore reasoning override. If we ever captured one on entry we
    // persist it back to the session; otherwise nothing to do.
    const prev = useConversationModeStore.getState().previousReasoningOverride
    if (restoreSid) {
      try {
        await chatApi.updateSessionReasoning(restoreSid, prev)
      } catch (err) {
        console.error('[ConversationMode] Failed to restore reasoning override:', err)
      }
    }
    useChatStore.getState().setReasoningOverride(prev)

    heldAudioRef.current = []
  }, [clearPendingBarge])

  // Entry effect: when `active` flips on, snapshot reasoning, force it off,
  // and start the VAD. When it flips off, tear everything down.
  const wasActiveRef = useRef(false)
  useEffect(() => {
    const wasActive = wasActiveRef.current
    wasActiveRef.current = active

    if (active && !wasActive) {
      if (!sessionId) {
        exitStore()
        return
      }

      const chatState = useChatStore.getState()
      const prevReasoning = chatState.reasoningOverride
      setPreviousReasoning(prevReasoning)

      chatState.setReasoningOverride(false)
      chatApi.updateSessionReasoning(sessionId, false).catch((err) => {
        console.error('[ConversationMode] Failed to set reasoning=false:', err)
      })

      // If a PTT session is in flight, stop it so we can grab the mic.
      try { voicePipeline.stopRecording() } catch { /* not active */ }

      audioCapture.startContinuous({
        onSpeechStart: handleSpeechStart,
        onSpeechEnd: handleSpeechEnd,
        onVolumeChange: () => {},
        onMisfire: handleMisfire,
      }).catch((err: unknown) => {
        console.error('[ConversationMode] Failed to start VAD:', err)
        useNotificationStore.getState().addNotification({
          level: 'error',
          title: 'Conversational mode failed',
          message: 'Could not access the microphone. Check browser permissions.',
        })
        exitStore()
      })
    }

    if (!active && wasActive) {
      const sid = sessionIdRef.current
      void teardown(sid)
    }
  }, [active, sessionId, handleSpeechStart, handleSpeechEnd, handleMisfire, exitStore, setPreviousReasoning, teardown])

  // If the caller removes availability while active, or we switch sessions,
  // exit conv-mode cleanly.
  useEffect(() => {
    if (active && !available) exitStore()
  }, [active, available, exitStore])

  // Hold-release with no held audio: if the user released the hold and no
  // VAD speech-end fired in the meantime, there's nothing buffered —
  // continue listening. If there IS buffered audio, it means the user
  // held through a quiet pause after an utterance; we dispatch it now so
  // the assistant doesn't wait forever.
  //
  // We only dispatch on release when (a) VAD is not currently tracking
  // ongoing speech (phase became 'user-speaking' without actively speaking
  // — but VAD doesn't expose that directly). Keep it simple: if any held
  // audio exists on release AND the phase is user-speaking, dispatch it.
  const prevHoldingRef = useRef(false)
  useEffect(() => {
    const wasHolding = prevHoldingRef.current
    prevHoldingRef.current = isHolding
    if (wasHolding && !isHolding) {
      if (heldAudioRef.current.length > 0) {
        const merged = flushHeldAudio(null)
        void transcribeAndSend(merged)
      }
    }
  }, [isHolding, flushHeldAudio, transcribeAndSend])

  // Observe chat stream to advance phase. `isWaitingForResponse` (set by
  // handleSend) + `isStreaming` (set when tokens arrive) together map to
  // thinking → speaking → listening.
  useEffect(() => {
    if (!active) return
    const current = phaseRef.current

    if (isStreaming || isWaitingForResponse) {
      if (current !== 'thinking' && current !== 'speaking') {
        setPhase('thinking')
      }
      return
    }

    // Not streaming and not waiting. If we were in the middle of a reply,
    // return to listening. Don't clobber user-speaking / held / transcribing.
    if (current === 'thinking' || current === 'speaking') {
      setPhase('listening')
    }
  }, [active, isStreaming, isWaitingForResponse, setPhase])

  // Reflect playback state: as soon as audioPlayback starts a segment we
  // should be in "speaking"; when the stream finishes and audio is quiet
  // we go back to listening. We poll audioPlayback.isPlaying() lightly —
  // it's a simple boolean read and avoids wiring new callbacks into the
  // playback module.
  useEffect(() => {
    if (!active) return
    const tick = window.setInterval(() => {
      const current = phaseRef.current
      if (!activeRef.current) return
      const playing = audioPlayback.isPlaying()
      if (playing && (current === 'thinking' || current === 'listening')) {
        setPhase('speaking')
      } else if (!playing && current === 'speaking') {
        // Only flip back if the chat stream is also finished.
        const cs = useChatStore.getState()
        if (!cs.isStreaming && !cs.isWaitingForResponse) {
          setPhase('listening')
        }
      }
    }, 150)
    return () => window.clearInterval(tick)
  }, [active, setPhase])

  // On unmount or session change: if conv-mode is active, exit cleanly.
  useEffect(() => {
    return () => {
      if (useConversationModeStore.getState().active) {
        const sid = sessionIdRef.current
        void teardown(sid)
        exitStore()
      }
    }
  }, [exitStore, teardown])

  useEffect(() => {
    if (active) exitStore()
    // Intentionally only on sessionId change; `active` is read to trigger
    // a synchronous exit when the user navigates mid-conversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])
}
