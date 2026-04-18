import { MicVAD } from '@ricky0123/vad-web'
import type { VoiceActivationThreshold } from '../stores/voiceSettingsStore'
import { VAD_PRESETS } from './vadPresets'

export interface AudioCaptureCallbacks {
  onSpeechStart: () => void
  onSpeechEnd: (audio: Float32Array) => void
  onVolumeChange: (level: number) => void
  /**
   * Continuous/VAD mode only: fired when a speech-start was a false positive
   * (noise burst too short to count as speech). Silero does NOT fire
   * onSpeechEnd in this case, so callers that optimistically transitioned to
   * "user-speaking" on speech-start need this to revert their state.
   */
  onMisfire?: () => void
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
  private pttSession = 0 // incremented on each start, checked after await

  // -- VAD (continuous) state --
  private vad: MicVAD | null = null
  private vadContext: AudioContext | null = null

  /**
   * Push-to-talk: record raw audio from mic. No VAD needed.
   * Call stopPTT() to get the recorded audio via onSpeechEnd.
   */
  async startPTT(callbacks: AudioCaptureCallbacks): Promise<void> {
    this.callbacks = callbacks
    this.pttChunks = []
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
    this.pttContext = new AudioContext({ sampleRate: 16_000 })
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

    callbacks.onSpeechStart()
  }

  /**
   * Stop PTT recording. Concatenates all chunks and delivers via onSpeechEnd.
   * Always calls onSpeechEnd (with empty audio if nothing was recorded).
   */
  stopPTT(): void {
    this.pttSession++ // invalidate any in-flight startPTT
    this.stopVolumeMeter()
    const cb = this.callbacks

    // Concatenate recorded chunks
    const totalLength = this.pttChunks.reduce((sum, c) => sum + c.length, 0)
    const audio = new Float32Array(totalLength)
    let offset = 0
    for (const chunk of this.pttChunks) {
      audio.set(chunk, offset)
      offset += chunk.length
    }
    this.pttChunks = []

    // Clean up audio nodes
    this.pttProcessor?.disconnect()
    this.pttProcessor = null
    this.pttStream?.getTracks().forEach((t) => t.stop())
    this.pttStream = null
    this.pttContext?.close()
    this.pttContext = null
    this.analyser = null
    this.callbacks = null

    // Always deliver — pipeline handles empty audio gracefully
    cb?.onSpeechEnd(audio)
  }

  /**
   * Continuous mode: use VAD to detect speech start/end automatically.
   * Call stopContinuous() to tear down.
   */
  async startContinuous(
    callbacks: AudioCaptureCallbacks,
    threshold: VoiceActivationThreshold = 'medium',
  ): Promise<void> {
    this.callbacks = callbacks

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

    this.vad = await MicVAD.new({
      getStream,
      onnxWASMBasePath: ORT_CDN,
      baseAssetPath: VAD_CDN,
      positiveSpeechThreshold: preset.positiveSpeechThreshold,
      negativeSpeechThreshold: preset.negativeSpeechThreshold,
      minSpeechMs: preset.minSpeechFrames * MS_PER_FRAME,
      redemptionMs: preset.redemptionFrames * MS_PER_FRAME,
      onSpeechStart: () => {
        this.callbacks?.onSpeechStart()
      },
      onSpeechEnd: (audio: Float32Array) => {
        this.callbacks?.onSpeechEnd(audio)
      },
      onVADMisfire: () => {
        this.callbacks?.onMisfire?.()
      },
    })

    if (capturedStream) {
      this.vadContext = new AudioContext()
      const source = this.vadContext.createMediaStreamSource(capturedStream)
      this.analyser = this.vadContext.createAnalyser()
      this.analyser.fftSize = 256
      source.connect(this.analyser)
      this.startVolumeMeter()
    }

    await this.vad.start()
  }

  /**
   * Stop continuous (VAD) recording.
   */
  stopContinuous(): void {
    this.stopVolumeMeter()
    this.vad?.pause()
    this.vad?.destroy()
    this.vad = null
    this.vadContext?.close()
    this.vadContext = null
    this.analyser = null
    this.callbacks = null
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
