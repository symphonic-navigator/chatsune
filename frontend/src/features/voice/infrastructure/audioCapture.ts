import { MicVAD } from '@ricky0123/vad-web'

export interface AudioCaptureCallbacks {
  onSpeechStart: () => void
  onSpeechEnd: (audio: Float32Array) => void
  onVolumeChange: (level: number) => void
}

// vad-web bundles its own onnxruntime-web (1.22.x, isolated by pnpm).
// We cannot configure that internal ORT instance from outside, so we
// let vad-web load ONNX Runtime WASM + VAD model from a CDN instead
// of trying to serve them from public/.
// This loads ~14 MB of code (WASM binary + model) — cached by browser after first load.
// No voice data is sent — only engine code is fetched.
const ORT_CDN = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/'
const VAD_CDN = 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.30/dist/'

class AudioCaptureImpl {
  private vad: MicVAD | null = null
  private callbacks: AudioCaptureCallbacks | null = null
  private analyser: AnalyserNode | null = null
  private animFrameId: number | null = null
  private audioContext: AudioContext | null = null

  async start(callbacks: AudioCaptureCallbacks): Promise<void> {
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

    this.vad = await MicVAD.new({
      getStream,
      onnxWASMBasePath: ORT_CDN,
      modelURL: VAD_CDN + 'silero_vad_legacy.onnx',
      onSpeechStart: () => {
        this.callbacks?.onSpeechStart()
      },
      onSpeechEnd: (audio: Float32Array) => {
        this.callbacks?.onSpeechEnd(audio)
      },
    })

    if (capturedStream) {
      this.audioContext = new AudioContext()
      const source = this.audioContext.createMediaStreamSource(capturedStream)
      this.analyser = this.audioContext.createAnalyser()
      this.analyser.fftSize = 256
      source.connect(this.analyser)
      this.startVolumeMeter()
    }

    await this.vad.start()
  }

  stop(): void {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId)
      this.animFrameId = null
    }
    this.vad?.pause()
    this.vad?.destroy()
    this.vad = null
    this.audioContext?.close()
    this.audioContext = null
    this.analyser = null
    this.callbacks = null
  }

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
}

export const audioCapture = new AudioCaptureImpl()
