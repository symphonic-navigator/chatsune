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
import { decideSttOutcome } from './bargeDecision'

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
    const sttBargeId = bargeIdRef.current

    if (audio.length === 0) {
      // No audio captured (e.g. held-release with nothing buffered). Treat
      // as "no barge confirmed" — resume if we're muted, otherwise just
      // return to listening.
      if (tentativeRef.current) {
        tentativeRef.current = false
        audioPlayback.resumeFromMute()
        setPhase('speaking')
      } else {
        setPhase('listening')
      }
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

      const outcome = decideSttOutcome({
        transcript: result.text,
        sttBargeId,
        currentBargeId: bargeIdRef.current,
      })

      if (outcome === 'stale') {
        // A newer barge has taken over while STT was running. Do nothing:
        // that newer cycle will run its own STT and decide.
        return
      }

      if (outcome === 'resume') {
        // No text → the noise was not a real barge. Resume playback, unless
        // we've hit the consecutive-resume cap (feedback-loop guard).
        if (tentativeRef.current) {
          tentativeRef.current = false
          consecutiveResumeRef.current += 1
          if (consecutiveResumeRef.current >= MAX_CONSECUTIVE_RESUMES) {
            // Likely TTS-bleed feedback loop — skip past the muted segment
            // instead of replaying it yet again.
            audioPlayback.discardMuted()
            consecutiveResumeRef.current = 0
            clearResumeReset()
          } else {
            audioPlayback.resumeFromMute()
            clearResumeReset()
            resumeResetTimerRef.current = setTimeout(() => {
              resumeResetTimerRef.current = null
              consecutiveResumeRef.current = 0
            }, RESUME_RESET_MS)
          }
          setPhase('speaking')
        } else {
          setPhase('listening')
        }
        return
      }

      // outcome === 'confirm' — commit to the barge.
      consecutiveResumeRef.current = 0
      clearResumeReset()
      if (tentativeRef.current) {
        tentativeRef.current = false
        cancelStreamingAutoRead()   // kills sentencer session + stopAll internally
        setActiveReader(null, 'idle')
      }
      setPhase('thinking')
      onSendRef.current(result.text.trim())
    } catch (err) {
      console.error('[ConversationMode] Transcription failed:', err)
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Transcription failed',
        message: "Couldn't transcribe audio — check the console for details.",
      })
      if (activeRef.current) {
        // On STT failure, err on the destructive side: tear down so the
        // user isn't left with muted playback forever.
        if (tentativeRef.current) {
          tentativeRef.current = false
          cancelStreamingAutoRead()
          setActiveReader(null, 'idle')
        }
        consecutiveResumeRef.current = 0
        clearResumeReset()
        setPhase('listening')
      }
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
  // Monotonic counter that identifies the current barge cycle. Incremented
  // every time a new speech-start is accepted (past the 150 ms misfire
  // window). Any async result (STT promise) that carries a stale bargeId is
  // ignored. This is the serialisation primitive for Tentative Barge.
  const bargeIdRef = useRef(0)
  // True while we are in TENTATIVE_BARGE — i.e. audio is muted but not yet
  // torn down. Used by handleSpeechStart to tell a "fresh" barge from a
  // repeat VAD re-trigger during the same user utterance.
  const tentativeRef = useRef(false)

  // Feedback-loop guard for tentative barges. When TTS audio bleeds through
  // the speakers into the mic, VAD may false-trigger on our own playback; STT
  // then returns empty ('resume'), we replay the muted segment from the
  // start, the same bleed re-triggers VAD, and we loop. After
  // MAX_CONSECUTIVE_RESUMES consecutive resume outcomes we instead DISCARD
  // the muted segment and let the queue carry on. A confirmed barge or a
  // quiet window of RESUME_RESET_MS resets the counter.
  const MAX_CONSECUTIVE_RESUMES = 3
  const RESUME_RESET_MS = 5000
  const consecutiveResumeRef = useRef(0)
  const resumeResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearResumeReset = () => {
    if (resumeResetTimerRef.current) {
      clearTimeout(resumeResetTimerRef.current)
      resumeResetTimerRef.current = null
    }
  }

  // True while Silero is tracking an utterance (between speech-start and the
  // matching speech-end / misfire). Read by the release useEffect to decide
  // whether to dispatch immediately or wait for the final speech-end.
  const vadActiveRef = useRef(false)

  // Safety fallback after hold release when VAD is still active: if Silero
  // never delivers its final speech-end (shouldn't happen, but guards against
  // a stuck VAD state), this timer flushes whatever is buffered so the user
  // isn't left waiting forever. See release useEffect below.
  const RELEASE_SAFETY_MS = 3000
  const releaseFallbackRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPendingBarge = useCallback(() => {
    if (pendingBargeRef.current) {
      clearTimeout(pendingBargeRef.current)
      pendingBargeRef.current = null
    }
  }, [])

  /**
   * Enter TENTATIVE_BARGE: mute playback instantly, but leave the TTS
   * synthesis pipeline, the sentence queue, and the LLM stream alone.
   * The fate of the barge is decided once STT returns.
   *
   * If we are already in TENTATIVE_BARGE (user re-triggered VAD mid-
   * utterance), we only bump bargeId so any in-flight STT becomes stale;
   * the earliest mute/anchor is kept (audioPlayback.mute is idempotent).
   */
  const executeBarge = useCallback(() => {
    pendingBargeRef.current = null
    bargeIdRef.current += 1
    const current = phaseRef.current
    if (current === 'thinking' || current === 'speaking') {
      audioPlayback.mute()
      tentativeRef.current = true
    }
    setPhase('user-speaking')
  }, [setPhase])

  /**
   * VAD speech-start handler. If the user speaks while the LLM is thinking
   * or a reply is playing, this schedules a Tentative Barge after
   * BARGE_DELAY_MS (the 150 ms misfire window). On fire, `executeBarge`
   * mutes playback without tearing down synthesis or the LLM stream; the
   * tear-down only happens once STT confirms a non-empty transcript (see
   * `transcribeAndSend`). If Silero retracts via `onVADMisfire` inside the
   * window, the pending barge is cancelled and nothing is muted.
   */
  const handleSpeechStart = useCallback(() => {
    vadActiveRef.current = true
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
    vadActiveRef.current = false
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
    if (releaseFallbackRef.current) {
      clearTimeout(releaseFallbackRef.current)
      releaseFallbackRef.current = null
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
    vadActiveRef.current = false
    if (pendingBargeRef.current) {
      clearPendingBarge()
      return
    }
    if (!activeRef.current) return
    if (holdingRef.current) return
    // If executeBarge already fired (150 ms elapsed before Silero retracted),
    // undo the tentative mute so audio resumes instead of staying silent.
    if (tentativeRef.current) {
      tentativeRef.current = false
      audioPlayback.resumeFromMute()
      setPhase('speaking')
      return
    }
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
    if (releaseFallbackRef.current) {
      clearTimeout(releaseFallbackRef.current)
      releaseFallbackRef.current = null
    }
    clearResumeReset()
    consecutiveResumeRef.current = 0
    // Tentative barges are torn down as if confirmed (conservative): when
    // the user leaves conv-mode or the session is disposed, we do NOT want
    // a muted audio source sitting around waiting for an STT result that
    // may never land.
    tentativeRef.current = false
    bargeIdRef.current += 1
    cancelStreamingAutoRead()

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

  // Hold-release: on release we check VAD's tracking state. If idle, dispatch
  // immediately. If active (user released mid-utterance), wait for the next
  // speech-end event which will merge the buffered chunks with the final one.
  // A longer safety fallback guards against VAD never delivering speech-end.
  const prevHoldingRef = useRef(false)
  useEffect(() => {
    const wasHolding = prevHoldingRef.current
    prevHoldingRef.current = isHolding
    if (wasHolding && !isHolding) {
      if (releaseFallbackRef.current) {
        clearTimeout(releaseFallbackRef.current)
        releaseFallbackRef.current = null
      }
      if (!vadActiveRef.current) {
        // VAD idle — the last speech-end has already landed. Dispatch whatever
        // we have buffered right away.
        if (heldAudioRef.current.length > 0) {
          const merged = flushHeldAudio(null)
          void transcribeAndSend(merged)
        }
        return
      }
      // VAD still tracking an utterance — wait for its speech-end, which will
      // merge the buffered chunks with the final one. The safety timer only
      // fires if that never happens.
      releaseFallbackRef.current = setTimeout(() => {
        releaseFallbackRef.current = null
        if (heldAudioRef.current.length > 0) {
          const merged = flushHeldAudio(null)
          void transcribeAndSend(merged)
        }
      }, RELEASE_SAFETY_MS)
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
