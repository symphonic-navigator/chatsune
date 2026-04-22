import { useCallback, useEffect, useRef } from 'react'
import { useConversationModeStore } from '../stores/conversationModeStore'
import { voicePipeline } from '../pipeline/voicePipeline'
import { audioCapture } from '../infrastructure/audioCapture'
import { useChatStore } from '../../../core/store/chatStore'
import { chatApi } from '../../../core/api/chat'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { resolveSTTEngine } from '../engines/resolver'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { pickRecordingMimeType, createRecorder } from '../infrastructure/audioRecording'
import { float32ToWavBlob } from '../infrastructure/wavEncoder'
import { createBargeController, type Barge, type BargeController } from '../bargeController'
import type { CapturedAudio } from '../types'

// One MediaRecorder instance per utterance (non-hold) or per hold-cycle
// (hold). The hook drives the lifecycle directly because the hold-cycle
// spans multiple VAD sub-segments and audioCapture's per-segment recorder
// would produce one blob per segment instead of one per utterance.
interface UtteranceRecorder {
  recorder: MediaRecorder
  mimeType: string
  chunks: Blob[]
  startedAt: number
}

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
   * Build and register a new ResponseTaskGroup for the voice-commit, returning
   * the new Group id. Must call registerActiveGroup internally (the registry's
   * supersede semantics take care of cancelling the predecessor). The caller
   * is also responsible for optimistic message insertion + setWaitingForResponse.
   */
  buildAndRegisterGroup: (correlationId: string, transcript: string) => string
  /**
   * Send the WebSocket chat.send (or chat.incognito.send) for the given
   * correlation id + transcript. Called immediately after buildAndRegisterGroup.
   */
  sendChatMessage: (correlationId: string, transcript: string) => void
}

/**
 * Controller for conversational voice mode.
 *
 * Owns the VAD lifecycle and the utterance-recorder plumbing. All barge
 * state flows through a `bargeController` instance held in a ref; this hook
 * no longer carries parallel state (no tentativeRef, no bargeIdRef, no
 * phaseRef). See devdocs/voice-barge-structural-redesign.md.
 *
 * The hook registers capture-level callbacks directly against
 * `audioCapture.startContinuous` (bypassing `voicePipeline.startRecording`)
 * so it can implement the hold-to-keep-talking gate without touching the
 * generic push-to-talk pipeline.
 */
export function useConversationMode({
  sessionId,
  available,
  buildAndRegisterGroup,
  sendChatMessage,
}: UseConversationModeOptions): void {
  const active = useConversationModeStore((s) => s.active)
  const isHolding = useConversationModeStore((s) => s.isHolding)
  const exitStore = useConversationModeStore((s) => s.exit)
  const setPreviousReasoning = useConversationModeStore((s) => s.setPreviousReasoning)
  const setCurrentBargeState = useConversationModeStore((s) => s.setCurrentBargeState)
  const setSttInFlight = useConversationModeStore((s) => s.setSttInFlight)
  const setVadActive = useConversationModeStore((s) => s.setVadActive)

  // Mirror isHolding into a ref so capture callbacks (which are created once
  // per listen-session) can read the current value without re-binding.
  const holdingRef = useRef(false)
  useEffect(() => { holdingRef.current = isHolding }, [isHolding])

  // Buffered PCM from VAD speech-end events. Multiple sub-segments accumulate
  // while the user holds "keep talking"; on release (or a later non-held
  // speech-end) the full buffer is concatenated into a single Float32Array
  // and bundled with the compressed blob for STT.
  const heldAudioRef = useRef<Float32Array[]>([])

  // Current utterance recorder. Starts on the first VAD speech-start OR on
  // hold-begin (whichever comes first), stops at dispatch time.
  const utteranceRecorderRef = useRef<UtteranceRecorder | null>(null)

  const activeRef = useRef(active)
  useEffect(() => { activeRef.current = active }, [active])

  // Refs so capture callbacks, built once, read fresh values.
  const buildAndRegisterGroupRef = useRef(buildAndRegisterGroup)
  useEffect(() => { buildAndRegisterGroupRef.current = buildAndRegisterGroup }, [buildAndRegisterGroup])
  const sendChatMessageRef = useRef(sendChatMessage)
  useEffect(() => { sendChatMessageRef.current = sendChatMessage }, [sendChatMessage])

  const sessionIdRef = useRef(sessionId)
  useEffect(() => { sessionIdRef.current = sessionId }, [sessionId])

  // Snapshot the user's VAD sensitivity preference into a ref so the entry
  // effect can read it without re-triggering when the setting changes
  // mid-session. Changes only take effect on the next entry into conv-mode.
  const voiceActivationThreshold = useVoiceSettingsStore((s) => s.voiceActivationThreshold)
  const voiceActivationThresholdRef = useRef(voiceActivationThreshold)
  useEffect(() => { voiceActivationThresholdRef.current = voiceActivationThreshold }, [voiceActivationThreshold])

  // Stable controller instance, created lazily once per hook lifetime.
  // Using a ref (rather than useMemo) guarantees identity is preserved even
  // under React 18 StrictMode's double-invoke of the render function.
  const controllerRef = useRef<BargeController | null>(null)
  if (controllerRef.current === null) {
    controllerRef.current = createBargeController({
      buildAndRegisterGroup: (corr, transcript) =>
        buildAndRegisterGroupRef.current(corr, transcript),
      sendChatMessage: (corr, transcript) =>
        sendChatMessageRef.current(corr, transcript),
      logger: {
        info: (...a) => console.info(...a),
        debug: (...a) => console.debug(...a),
        warn: (...a) => console.warn(...a),
        error: (...a) => console.error(...a),
      },
    })
  }
  const controller = controllerRef.current

  // Direct reference to the in-flight Barge so handleMisfire can mark it
  // stale and transcribeAndSend can call commit/resume on it. Referential
  // identity is how the controller detects staleness, so we never copy this.
  const currentBargeRef = useRef<Barge | null>(null)

  // Helper that pushes the controller's current Barge state into the store
  // so usePhase picks it up reactively.
  const publishBargeState = useCallback(() => {
    setCurrentBargeState(controller.current?.state ?? null)
  }, [controller, setCurrentBargeState])

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

  /**
   * Start an utterance recorder if one isn't already running. Called from:
   *  - VAD speech-start (first utterance of a non-hold cycle)
   *  - Hold-begin (cover speech that started before VAD crossed the threshold)
   *
   * No-op when a recorder is already running or when MediaRecorder is
   * unavailable — the Tier-3 WAV fallback is built from buffered PCM at
   * dispatch time.
   */
  const ensureRecorderStarted = useCallback((): void => {
    if (utteranceRecorderRef.current) return
    const stream = audioCapture.getMediaStream()
    if (!stream) return
    const mime = pickRecordingMimeType()
    if (!mime) return
    try {
      const recorder = createRecorder(stream, mime)
      const chunks: Blob[] = []
      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) chunks.push(ev.data)
      }
      recorder.start()
      utteranceRecorderRef.current = {
        recorder,
        mimeType: mime,
        chunks,
        startedAt: performance.now(),
      }
    } catch (err) {
      console.warn('[ConversationMode] MediaRecorder start failed:', err)
      utteranceRecorderRef.current = null
    }
  }, [])

  /**
   * Finalise the current utterance recorder, waiting for its final
   * `dataavailable` + `onstop`. Resolves with the upload-ready bundle
   * (compressed if available, WAV fallback otherwise). `pcm` is the
   * caller-provided Float32 merge.
   */
  const finaliseRecorderAndBundle = useCallback(
    (pcm: Float32Array): Promise<CapturedAudio> => {
      const state = utteranceRecorderRef.current
      utteranceRecorderRef.current = null
      const fallback: CapturedAudio = {
        pcm,
        blob: float32ToWavBlob(pcm, 16_000),
        mimeType: 'audio/wav',
        sampleRate: 16_000,
        durationMs: pcm.length > 0 ? (pcm.length / 16_000) * 1000 : 0,
      }
      if (!state) return Promise.resolve(fallback)

      return new Promise<CapturedAudio>((resolve) => {
        const finalise = (): void => {
          const durationMs = Math.max(0, performance.now() - state.startedAt)
          const blob = new Blob(state.chunks, { type: state.mimeType })
          if (blob.size === 0) {
            resolve(fallback)
            return
          }
          resolve({
            pcm,
            blob,
            mimeType: state.mimeType,
            sampleRate: 0,
            durationMs,
          })
        }
        state.recorder.addEventListener('stop', finalise, { once: true })
        try {
          if (state.recorder.state !== 'inactive') state.recorder.stop()
          else finalise()
        } catch {
          finalise()
        }
      })
    },
    [],
  )

  /**
   * Abort (not stop) the current utterance recorder. Discards any pending
   * bundle. Used on generation bumps, teardown, or any path where we know
   * the bundle must not be uploaded.
   */
  const abortRecorder = useCallback((): void => {
    const state = utteranceRecorderRef.current
    utteranceRecorderRef.current = null
    if (!state) return
    try {
      if (state.recorder.state !== 'inactive') state.recorder.stop()
    } catch { /* already stopped */ }
  }, [])

  // Run STT against an already-captured CapturedAudio and hand the outcome
  // to the barge controller. Called when the user's utterance ends (release
  // or normal VAD speech-end while not holding).
  const transcribeAndSend = useCallback(async (audio: CapturedAudio): Promise<void> => {
    // Speech-end can arrive without a VAD speech-start having crossed the
    // 150 ms pending-barge window — e.g. an ultra-short utterance. Create a
    // Barge now so the controller sees a consistent lifecycle and picks up
    // the currently-active Group as its pause target.
    const barge = currentBargeRef.current ?? controller.start()
    currentBargeRef.current = barge
    publishBargeState()

    if (!activeRef.current) {
      controller.abandonAll()
      currentBargeRef.current = null
      publishBargeState()
      return
    }

    if (audio.pcm.length === 0 && audio.blob.size === 0) {
      // No audio captured (e.g. held-release with nothing buffered). Treat
      // as "no barge confirmed" — resume the paused Group (if any).
      controller.resume(barge)
      currentBargeRef.current = null
      publishBargeState()
      return
    }

    const stt = resolveSTTEngine()
    if (!stt) {
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Conversational mode stopped',
        message: 'No transcription engine is available.',
      })
      controller.abandonAll()
      currentBargeRef.current = null
      publishBargeState()
      exitStore()
      return
    }

    // Mark STT in flight so usePhase can show 'transcribing'.
    setSttInFlight(true)
    let result: { text: string }
    try {
      result = await stt.transcribe(audio)
    } catch (err) {
      console.error('[ConversationMode] Transcription failed:', err)
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Transcription failed',
        message: "Couldn't transcribe audio — check the console for details.",
      })
      setSttInFlight(false)
      if (activeRef.current) {
        // On STT failure err on the destructive side: drop the Barge and
        // cancel the active Group so the user isn't left with muted playback.
        controller.abandonAll()
      }
      currentBargeRef.current = null
      publishBargeState()
      return
    }
    setSttInFlight(false)

    if (!activeRef.current || barge.state !== 'pending-stt') {
      // Teardown / misfire already transitioned this Barge. Controller has
      // already been told; nothing more to do here.
      currentBargeRef.current = null
      publishBargeState()
      return
    }

    if (result.text.trim() === '') {
      controller.resume(barge)
    } else {
      controller.commit(barge, result.text.trim())
    }
    currentBargeRef.current = null
    publishBargeState()
  }, [controller, exitStore, publishBargeState, setSttInFlight])

  // Silero fires onSpeechStart on any loud-enough frame — including brief
  // non-speech noise (chair creaks, keyboard clicks) that later turns out to
  // be a misfire. Reacting immediately would cut off playback for those
  // bursts. Instead we defer the barge by BARGE_DELAY_MS; if a misfire
  // arrives inside that window, the pending barge is cancelled and playback
  // continues untouched. Real speech typically lasts longer than this.
  const BARGE_DELAY_MS = 150
  const pendingBargeRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // True while Silero is tracking an utterance (between speech-start and the
  // matching speech-end / misfire). Read by the release useEffect to decide
  // whether to dispatch immediately or wait for the final speech-end.
  const vadActiveRef = useRef(false)

  // Safety fallback after hold release when VAD is still active.
  const RELEASE_SAFETY_MS = 3000
  const releaseFallbackRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPendingBarge = useCallback(() => {
    if (pendingBargeRef.current) {
      clearTimeout(pendingBargeRef.current)
      pendingBargeRef.current = null
    }
  }, [])

  /**
   * Create a new Barge via the controller. The controller handles pausing
   * the active Group internally. Captures the Barge in a ref so the later
   * STT path (and handleMisfire) can hand it back for commit/resume/stale.
   */
  const executeBarge = useCallback(() => {
    pendingBargeRef.current = null
    currentBargeRef.current = controller.start()
    publishBargeState()
  }, [controller, publishBargeState])

  /**
   * VAD speech-start handler. Schedules a deferred barge after
   * BARGE_DELAY_MS; if Silero retracts via `onVADMisfire` inside the window,
   * the pending barge is cancelled and nothing is muted.
   */
  const handleSpeechStart = useCallback(() => {
    vadActiveRef.current = true
    setVadActive(true)
    if (!activeRef.current) return
    clearPendingBarge()
    pendingBargeRef.current = setTimeout(executeBarge, BARGE_DELAY_MS)
    // Start the utterance recorder on the first speech-start of a cycle.
    // If a hold-begin already started it, this is a no-op.
    ensureRecorderStarted()
  }, [executeBarge, clearPendingBarge, ensureRecorderStarted, setVadActive])

  /**
   * VAD speech-end handler. Two cases:
   *   (a) user is holding — buffer the audio, stay in user-speaking.
   *   (b) user is NOT holding — concatenate + ship off to STT.
   */
  const handleSpeechEnd = useCallback((audio: CapturedAudio) => {
    vadActiveRef.current = false
    setVadActive(false)
    if (!activeRef.current) return
    if (pendingBargeRef.current) {
      clearPendingBarge()
      executeBarge()
    }
    if (holdingRef.current) {
      if (audio.pcm.length > 0) heldAudioRef.current.push(audio.pcm)
      return
    }
    if (releaseFallbackRef.current) {
      clearTimeout(releaseFallbackRef.current)
      releaseFallbackRef.current = null
    }
    const merged = flushHeldAudio(audio.pcm)
    void finaliseRecorderAndBundle(merged).then((bundle) => transcribeAndSend(bundle))
  }, [flushHeldAudio, transcribeAndSend, clearPendingBarge, executeBarge, finaliseRecorderAndBundle, setVadActive])

  /**
   * VAD misfire handler. If the deferred barge is still pending, drop it —
   * the noise burst never became real speech. If the Barge has already been
   * created (150 ms elapsed before Silero retracted), tell the controller to
   * mark it stale; the controller will un-pause the Group iff it still
   * matches the one we paused. During hold we keep the overlay visible —
   * misfires between utterances are expected.
   */
  const handleMisfire = useCallback(() => {
    vadActiveRef.current = false
    setVadActive(false)
    if (pendingBargeRef.current) {
      clearPendingBarge()
      return
    }
    if (!activeRef.current) return
    if (holdingRef.current) return
    const barge = currentBargeRef.current
    if (barge) {
      controller.stale(barge)
      currentBargeRef.current = null
      publishBargeState()
    }
  }, [controller, clearPendingBarge, publishBargeState, setVadActive])

  /**
   * Teardown — stop VAD, cancel the active Group via the controller, and
   * restore session settings. `abandonAll` handles both the Barge transition
   * and the Group cancel in one step.
   */
  const teardown = useCallback(async (restoreSid: string | null) => {
    // Abort any in-flight utterance recorder BEFORE stopContinuous tears down
    // the media stream — once the tracks are gone the recorder's final chunk
    // may arrive empty and we don't want a stale bundle to be dispatched.
    abortRecorder()
    try { audioCapture.stopContinuous() } catch { /* not active */ }
    clearPendingBarge()
    if (releaseFallbackRef.current) {
      clearTimeout(releaseFallbackRef.current)
      releaseFallbackRef.current = null
    }
    // abandonAll covers: marking the Barge abandoned, clearing the
    // controller slot, and cancelling the active Group with reason 'teardown'.
    controller.abandonAll()
    currentBargeRef.current = null
    publishBargeState()
    setSttInFlight(false)
    setVadActive(false)

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
  }, [clearPendingBarge, abortRecorder, controller, publishBargeState, setSttInFlight, setVadActive])

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
      }, {
        threshold: voiceActivationThresholdRef.current,
        // We drive our own per-hold-cycle MediaRecorder lifecycle. The blob
        // delivered by audioCapture in external-recorder mode is the Tier-3
        // WAV fallback and is ignored here.
        externalRecorder: true,
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
  const prevHoldingRef = useRef(false)
  useEffect(() => {
    const wasHolding = prevHoldingRef.current
    prevHoldingRef.current = isHolding

    if (!wasHolding && isHolding) {
      // Hold-begin: make sure a recorder is running so the whole hold-cycle
      // is captured as one blob.
      ensureRecorderStarted()
      return
    }

    if (wasHolding && !isHolding) {
      if (releaseFallbackRef.current) {
        clearTimeout(releaseFallbackRef.current)
        releaseFallbackRef.current = null
      }
      if (!vadActiveRef.current) {
        if (heldAudioRef.current.length > 0 || utteranceRecorderRef.current) {
          const merged = flushHeldAudio(null)
          void finaliseRecorderAndBundle(merged).then((bundle) => transcribeAndSend(bundle))
        }
        return
      }
      releaseFallbackRef.current = setTimeout(() => {
        releaseFallbackRef.current = null
        if (heldAudioRef.current.length > 0 || utteranceRecorderRef.current) {
          const merged = flushHeldAudio(null)
          void finaliseRecorderAndBundle(merged).then((bundle) => transcribeAndSend(bundle))
        }
      }, RELEASE_SAFETY_MS)
    }
  }, [isHolding, flushHeldAudio, transcribeAndSend, finaliseRecorderAndBundle, ensureRecorderStarted])

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
    // Read live from the store rather than the render-time closure: if
    // the user enters conv-mode and switches session in the same batch,
    // the closure would still see `active=false` even though the store
    // has already flipped true, leaving the new session in a half-entered
    // state.
    if (useConversationModeStore.getState().active) exitStore()
  }, [sessionId, exitStore])
}
