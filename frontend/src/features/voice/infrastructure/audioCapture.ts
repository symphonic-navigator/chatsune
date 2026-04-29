import { MicVAD } from '@ricky0123/vad-web'
import type { VoiceActivationThreshold } from '../stores/voiceSettingsStore'
import { VOICE_REDEMPTION_MS_DEFAULT } from '../stores/voiceSettingsStore'
import { VAD_PRESETS } from './vadPresets'
import type { CapturedAudio } from '../types'
import { pickRecordingMimeType, createRecorder } from './audioRecording'
import { float32ToWavBlob } from './wavEncoder'
import { usePauseRedemptionStore } from '../stores/pauseRedemptionStore'

export interface AudioCaptureCallbacks {
  onSpeechStart: () => void
  /**
   * Fired when a captured utterance is ready. `audio.pcm` is the raw 16 kHz
   * mono Float32 stream from VAD/ScriptProcessor; `audio.blob` is the
   * upload-ready payload (compressed Opus/AAC when available, WAV when
   * falling back to Tier 3).
   */
  onSpeechEnd: (audio: CapturedAudio) => void
  onVolumeChange: (level: number) => void
  /**
   * Continuous/VAD mode only: fired when a speech-start was a false positive
   * (noise burst too short to count as speech). Silero does NOT fire
   * onSpeechEnd in this case, so callers that optimistically transitioned to
   * "user-speaking" on speech-start need this to revert their state.
   */
  onMisfire?: () => void
}

export interface StartContinuousOptions {
  threshold?: VoiceActivationThreshold
  /**
   * When `true`, audioCapture does NOT start its own MediaRecorder around
   * each VAD segment. The caller takes ownership of recording via
   * `getMediaStream()` and drives its own lifecycle. `onSpeechEnd` still
   * fires, but the delivered `CapturedAudio.blob` is the Tier-3 WAV
   * derived from the PCM — the caller is expected to ignore that blob
   * and attach its own blob to the utterance before handing it to STT.
   *
   * This is used by `useConversationMode`, which runs one MediaRecorder
   * per hold-cycle spanning multiple VAD sub-segments.
   */
  externalRecorder?: boolean
  /**
   * VAD redemption window in ms. When omitted, falls back to
   * `VOICE_REDEMPTION_MS_DEFAULT` from voiceSettingsStore.
   */
  redemptionMs?: number
}

// vad-web bundles its own onnxruntime-web (1.22.x, isolated by pnpm).
// We cannot configure that internal ORT instance from outside, so we
// let vad-web load ONNX Runtime WASM + VAD model from CDN instead of
// trying to serve them from public/ (Vite 8 blocks .mjs from public/).
//
// baseAssetPath: used for both the VAD model AND the AudioWorklet JS
// onnxWASMBasePath: used for ONNX Runtime .wasm + .mjs files
//
// ~14 MB total (WASM + model) — browser-cached after first load.
// Only engine code is fetched — no voice data leaves the browser.
const ORT_CDN = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/'
const VAD_CDN = 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/'

// Target sample rate for VAD-path PCM. MediaRecorder records at the
// browser's native rate (typically 48 kHz), but the PCM we build the
// Tier-3 WAV from comes from the 16 kHz AudioContext.
const VAD_SAMPLE_RATE = 16_000

class AudioCaptureImpl {
  // -- shared state --
  private callbacks: AudioCaptureCallbacks | null = null
  private analyser: AnalyserNode | null = null
  private animFrameId: number | null = null

  // -- PTT state --
  private pttContext: AudioContext | null = null
  private pttStream: MediaStream | null = null
  private pttProcessor: ScriptProcessorNode | null = null
  private pttChunks: Float32Array[] = []
  private pttStartedAt = 0
  private pttSession = 0 // incremented on each start, checked after await
  private pttRecorder: MediaRecorder | null = null
  private pttRecorderMime: string | null = null
  private pttRecorderChunks: Blob[] = []

  // -- VAD (continuous) state --
  private vad: MicVAD | null = null
  private vadContext: AudioContext | null = null
  private vadStream: MediaStream | null = null
  private vadRecorder: MediaRecorder | null = null
  private vadRecorderMime: string | null = null
  private vadRecorderChunks: Blob[] = []
  private vadSegmentStartedAt = 0
  private vadExternalRecorder = false

  // -- Silence-edge state machine (drives pauseRedemptionStore) --

  /** Number of consecutive frames whose probability sat below negativeSpeechThreshold. */
  private silenceFrames = 0
  /** True while VAD has confirmed a speech segment (between speech-start and speech-end). */
  private inSpeechSegment = false
  /** True while pauseRedemptionStore is currently open (we own the toggle). */
  private redemptionOpen = false
  /** Snapshotted positiveSpeechThreshold for the current session — set in startContinuous. */
  private framePosThreshold = 0.65
  /** Snapshotted negativeSpeechThreshold for the current session — set in startContinuous. */
  private frameNegThreshold = 0.5
  /** Snapshotted redemption window in ms for the current session — set in startContinuous. */
  private currentRedemptionMs = 1_728

  /**
   * 4 frames × 96 ms/frame = 384 ms grace before the redemption pie may appear.
   * Frame-counted (not wall-clock) so it is robust against VAD frame-cadence jitter.
   */
  private static readonly GRACE_FRAMES = 4

  /**
   * Returns the active MediaStream (PTT or continuous/VAD), or `null` if
   * no capture session is running. Used by callers who run their own
   * MediaRecorder lifecycle (e.g. conversation mode's hold-cycle
   * recording).
   */
  getMediaStream(): MediaStream | null {
    return this.pttStream ?? this.vadStream ?? null
  }

  /**
   * Push-to-talk: record raw audio from mic. No VAD needed.
   * Call stopPTT() to get the recorded audio via onSpeechEnd.
   */
  async startPTT(callbacks: AudioCaptureCallbacks): Promise<void> {
    this.callbacks = callbacks
    this.pttChunks = []
    this.pttRecorderChunks = []
    const session = ++this.pttSession

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })

    // If stopPTT was called while we were awaiting getUserMedia, abort
    if (session !== this.pttSession) {
      stream.getTracks().forEach((t) => t.stop())
      return
    }

    this.pttStream = stream
    this.pttContext = new AudioContext({ sampleRate: VAD_SAMPLE_RATE })
    const source = this.pttContext.createMediaStreamSource(this.pttStream)

    // Collect raw PCM samples
    this.pttProcessor = this.pttContext.createScriptProcessor(4096, 1, 1)
    this.pttProcessor.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0)
      this.pttChunks.push(new Float32Array(data))
    }
    source.connect(this.pttProcessor)
    this.pttProcessor.connect(this.pttContext.destination)

    // Volume meter
    this.analyser = this.pttContext.createAnalyser()
    this.analyser.fftSize = 256
    source.connect(this.analyser)
    this.startVolumeMeter()

    // Parallel compressed recording. If no supported MIME type, fall
    // through to Tier-3 WAV at stop() time.
    //
    // Bind the chunk array as a closure variable rather than reading
    // `this.pttRecorderChunks` inside the callback. `recorder.stop()`
    // delivers its final `dataavailable` event asynchronously, after
    // stopPTT() has already moved the instance field into a local
    // reference; reading `this` at that point would write into a stale
    // array and produce an empty blob (triggering the WAV fallback).
    this.pttRecorderMime = pickRecordingMimeType()
    if (this.pttRecorderMime) {
      try {
        this.pttRecorder = createRecorder(stream, this.pttRecorderMime)
        const chunks = this.pttRecorderChunks
        this.pttRecorder.ondataavailable = (ev) => {
          if (ev.data && ev.data.size > 0) chunks.push(ev.data)
        }
        this.pttRecorder.start()
      } catch (err) {
        console.warn('[audioCapture] MediaRecorder start failed, falling back to WAV:', err)
        this.pttRecorder = null
        this.pttRecorderMime = null
      }
    }

    this.pttStartedAt = performance.now()
    callbacks.onSpeechStart()
  }

  /**
   * Stop PTT recording. Concatenates all chunks and delivers via onSpeechEnd.
   * Always calls onSpeechEnd (with empty audio if nothing was recorded).
   *
   * Teardown order matters: the MediaRecorder must be allowed to flush its
   * final `dataavailable` + `stop` events BEFORE the MediaStream tracks and
   * AudioContext nodes go away. If the tracks die first, Chrome emits an
   * empty final chunk and we fall back to WAV — which defeats the whole
   * parallel-recording pipeline. `teardown()` is idempotent and is invoked
   * from every terminal branch exactly once, after the recorder is done.
   */
  stopPTT(): void {
    this.pttSession++ // invalidate any in-flight startPTT
    this.stopVolumeMeter()
    const cb = this.callbacks

    // Concatenate recorded PCM chunks
    const totalLength = this.pttChunks.reduce((sum, c) => sum + c.length, 0)
    const pcm = new Float32Array(totalLength)
    let offset = 0
    for (const chunk of this.pttChunks) {
      pcm.set(chunk, offset)
      offset += chunk.length
    }
    this.pttChunks = []
    const durationMs = Math.max(0, performance.now() - this.pttStartedAt)

    const recorder = this.pttRecorder
    const mime = this.pttRecorderMime
    const chunks = this.pttRecorderChunks
    const stream = this.pttStream
    this.pttRecorder = null
    this.pttRecorderMime = null
    this.pttRecorderChunks = []
    this.pttStream = null
    this.callbacks = null

    let tornDown = false
    const teardown = (): void => {
      if (tornDown) return
      tornDown = true
      this.pttProcessor?.disconnect()
      this.pttProcessor = null
      stream?.getTracks().forEach((t) => t.stop())
      this.pttContext?.close()
      this.pttContext = null
      this.analyser = null
    }

    const deliver = (blob: Blob, mimeType: string, sampleRate: number): void => {
      cb?.onSpeechEnd({ pcm, blob, mimeType, sampleRate, durationMs })
    }

    // If a Tier-1/2 recorder was running, wait for its final dataavailable
    // via onstop before tearing down the stream and building the bundle.
    // Otherwise derive WAV from PCM immediately.
    if (recorder && mime) {
      const finalise = (): void => {
        const blob = new Blob(chunks, { type: mime })
        teardown()
        if (blob.size > 0) {
          // MediaRecorder doesn't reliably expose its actual sample rate;
          // report 0 to signal "server-negotiated / container-embedded".
          deliver(blob, mime, 0)
        } else {
          // Recorder produced no bytes (very short PTT). Fall back to WAV
          // so the STT engine still gets something to chew on.
          deliver(float32ToWavBlob(pcm, VAD_SAMPLE_RATE), 'audio/wav', VAD_SAMPLE_RATE)
        }
      }
      recorder.addEventListener('stop', finalise, { once: true })
      try {
        if (recorder.state !== 'inactive') recorder.stop()
        else finalise()
      } catch {
        finalise()
      }
    } else {
      teardown()
      deliver(float32ToWavBlob(pcm, VAD_SAMPLE_RATE), 'audio/wav', VAD_SAMPLE_RATE)
    }
  }

  /**
   * Continuous mode: use VAD to detect speech start/end automatically.
   * Call stopContinuous() to tear down.
   *
   * Legacy call-site form (`threshold` only) is still accepted. New callers
   * should pass an options object so `externalRecorder` can be set.
   */
  async startContinuous(
    callbacks: AudioCaptureCallbacks,
    thresholdOrOptions: VoiceActivationThreshold | StartContinuousOptions = 'medium',
  ): Promise<void> {
    this.callbacks = callbacks

    const options: StartContinuousOptions = typeof thresholdOrOptions === 'string'
      ? { threshold: thresholdOrOptions }
      : thresholdOrOptions
    const threshold: VoiceActivationThreshold = options.threshold ?? 'medium'
    this.vadExternalRecorder = options.externalRecorder === true

    let capturedStream: MediaStream | null = null
    const getStream = async (): Promise<MediaStream> => {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      capturedStream = stream
      return stream
    }

    // vad-web 0.0.30 exposes redemption / min-speech durations as *Ms, not
    // *Frames, on its public API. The presets are authored in frames for
    // readability; convert here. Default Silero model is "legacy" → 1536
    // samples per frame at 16 kHz ⇒ 96 ms per frame.
    const preset = VAD_PRESETS[threshold]
    const MS_PER_FRAME = 96

    // Prefer the caller-supplied value; fall back to the store default so
    // legacy callers (e.g. voicePipeline) that pass no options get the same
    // numerical default (1728 ms) from a single source of truth.
    const effectiveRedemptionMs = options.redemptionMs ?? VOICE_REDEMPTION_MS_DEFAULT

    // Snapshot threshold values and reset state-machine fields for this session.
    this.framePosThreshold = preset.positiveSpeechThreshold
    this.frameNegThreshold = preset.negativeSpeechThreshold
    this.currentRedemptionMs = effectiveRedemptionMs
    this.silenceFrames = 0
    this.inSpeechSegment = false
    this.redemptionOpen = false

    this.vad = await MicVAD.new({
      getStream,
      onnxWASMBasePath: ORT_CDN,
      baseAssetPath: VAD_CDN,
      positiveSpeechThreshold: preset.positiveSpeechThreshold,
      negativeSpeechThreshold: preset.negativeSpeechThreshold,
      minSpeechMs: preset.minSpeechFrames * MS_PER_FRAME,
      redemptionMs: effectiveRedemptionMs,
      onSpeechStart: () => {
        this.handleVadSpeechStart()
      },
      onSpeechEnd: (audio: Float32Array) => {
        this.handleVadSpeechEnd(audio)
      },
      onVADMisfire: () => {
        this.handleVadMisfire()
      },
      onFrameProcessed: (probs: { isSpeech: number }) => {
        this.handleVadFrame(probs)
      },
    })

    if (capturedStream) {
      this.vadStream = capturedStream
      this.vadContext = new AudioContext()
      const source = this.vadContext.createMediaStreamSource(capturedStream)
      this.analyser = this.vadContext.createAnalyser()
      this.analyser.fftSize = 256
      source.connect(this.analyser)
      this.startVolumeMeter()
    }

    await this.vad.start()
  }

  private handleVadSpeechStart(): void {
    this.inSpeechSegment = true
    this.silenceFrames = 0
    this.vadSegmentStartedAt = performance.now()
    // External-recorder mode: caller (e.g. useConversationMode) owns
    // recording lifecycle. We only forward the VAD edge.
    if (!this.vadExternalRecorder && this.vadStream) {
      const mime = pickRecordingMimeType()
      this.vadRecorderMime = mime
      this.vadRecorderChunks = []
      if (mime) {
        try {
          this.vadRecorder = createRecorder(this.vadStream, mime)
          // Bind the chunk array in a closure — see the matching PTT
          // path for the rationale; without this, the final async
          // dataavailable event writes into a reset instance field.
          const chunks = this.vadRecorderChunks
          this.vadRecorder.ondataavailable = (ev) => {
            if (ev.data && ev.data.size > 0) chunks.push(ev.data)
          }
          this.vadRecorder.start()
        } catch (err) {
          console.warn('[audioCapture] VAD MediaRecorder start failed:', err)
          this.vadRecorder = null
          this.vadRecorderMime = null
        }
      }
    }
    this.callbacks?.onSpeechStart()
  }

  private handleVadSpeechEnd(pcm: Float32Array): void {
    this.inSpeechSegment = false
    this.silenceFrames = 0
    if (this.redemptionOpen) {
      this.redemptionOpen = false
      usePauseRedemptionStore.getState().clear()
    }
    const cb = this.callbacks
    const durationMs = Math.max(0, performance.now() - this.vadSegmentStartedAt)

    const deliver = (blob: Blob, mimeType: string, sampleRate: number): void => {
      cb?.onSpeechEnd({ pcm, blob, mimeType, sampleRate, durationMs })
    }

    if (this.vadExternalRecorder) {
      // Caller will attach its own blob. Deliver Tier-3 WAV as a "best-effort"
      // payload so the bundle is valid if the caller happens to use it.
      deliver(float32ToWavBlob(pcm, VAD_SAMPLE_RATE), 'audio/wav', VAD_SAMPLE_RATE)
      return
    }

    const recorder = this.vadRecorder
    const mime = this.vadRecorderMime
    const chunks = this.vadRecorderChunks
    this.vadRecorder = null
    this.vadRecorderMime = null
    this.vadRecorderChunks = []

    if (recorder && mime) {
      const finalise = (): void => {
        const blob = new Blob(chunks, { type: mime })
        if (blob.size > 0) {
          deliver(blob, mime, 0)
        } else {
          deliver(float32ToWavBlob(pcm, VAD_SAMPLE_RATE), 'audio/wav', VAD_SAMPLE_RATE)
        }
      }
      recorder.addEventListener('stop', finalise, { once: true })
      try {
        if (recorder.state !== 'inactive') recorder.stop()
        else finalise()
      } catch {
        finalise()
      }
    } else {
      deliver(float32ToWavBlob(pcm, VAD_SAMPLE_RATE), 'audio/wav', VAD_SAMPLE_RATE)
    }
  }

  private handleVadMisfire(): void {
    this.inSpeechSegment = false
    this.silenceFrames = 0
    if (this.redemptionOpen) {
      this.redemptionOpen = false
      usePauseRedemptionStore.getState().clear()
    }
    // Drop the recorder silently — no utterance to deliver.
    const recorder = this.vadRecorder
    this.vadRecorder = null
    this.vadRecorderMime = null
    this.vadRecorderChunks = []
    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch { /* already stopped */ }
    }
    this.callbacks?.onMisfire?.()
  }

  /**
   * Called on every VAD frame while continuous mode is running (~96 ms cadence).
   *
   * Maintains a running silence counter. Once `GRACE_FRAMES` consecutive frames
   * fall below `frameNegThreshold` inside an active speech segment, the pause
   * redemption window opens. Any frame that climbs back above `framePosThreshold`
   * resets the counter (and closes the window if it was open).
   *
   * The grace period is frame-counted rather than wall-clock-counted so that
   * it is robust against any jitter in the VAD's frame cadence.
   */
  private handleVadFrame(probs: { isSpeech: number }): void {
    if (!this.inSpeechSegment) return

    if (probs.isSpeech < this.frameNegThreshold) {
      this.silenceFrames += 1
      if (!this.redemptionOpen && this.silenceFrames >= AudioCaptureImpl.GRACE_FRAMES) {
        this.redemptionOpen = true
        usePauseRedemptionStore.getState().start(this.currentRedemptionMs)
      }
      return
    }

    // Probability rose again — reset the silence counter.
    this.silenceFrames = 0
    // Hysteresis: stay open while probability sits in the ambiguous band
    // between negative and positive thresholds. Closing the redemption
    // requires a frame that crosses fully back into "speech".
    if (this.redemptionOpen && probs.isSpeech > this.framePosThreshold) {
      this.redemptionOpen = false
      usePauseRedemptionStore.getState().clear()
    }
  }

  /**
   * Stop continuous (VAD) recording.
   */
  stopContinuous(): void {
    this.inSpeechSegment = false
    this.silenceFrames = 0
    if (this.redemptionOpen) {
      this.redemptionOpen = false
      usePauseRedemptionStore.getState().clear()
    }
    this.stopVolumeMeter()
    this.vad?.pause()
    this.vad?.destroy()
    this.vad = null
    // If a VAD segment was mid-recording, abort (not stop) to discard the
    // in-flight blob — the caller has torn down, nothing will consume it.
    const recorder = this.vadRecorder
    this.vadRecorder = null
    this.vadRecorderMime = null
    this.vadRecorderChunks = []
    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch { /* ignore */ }
    }
    this.vadStream = null
    this.vadContext?.close()
    this.vadContext = null
    this.analyser = null
    this.callbacks = null
    this.vadExternalRecorder = false
  }

  // -- Volume meter (shared) --

  private startVolumeMeter(): void {
    if (!this.analyser || !this.callbacks) return
    const dataArray = new Uint8Array(this.analyser.frequencyBinCount)
    const tick = () => {
      if (!this.analyser) return
      this.analyser.getByteFrequencyData(dataArray)
      const sum = dataArray.reduce((a, b) => a + b, 0)
      const level = sum / (dataArray.length * 255)
      this.callbacks?.onVolumeChange(level)
      this.animFrameId = requestAnimationFrame(tick)
    }
    this.animFrameId = requestAnimationFrame(tick)
  }

  private stopVolumeMeter(): void {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId)
      this.animFrameId = null
    }
  }
}

export const audioCapture = new AudioCaptureImpl()

/**
 * Named export of the implementation class so that unit tests can instantiate
 * isolated instances (rather than sharing the module-level singleton).
 */
export { AudioCaptureImpl as AudioCapture }
