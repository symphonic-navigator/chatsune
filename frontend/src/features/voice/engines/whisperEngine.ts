import { pipeline, AutomaticSpeechRecognitionPipeline } from '@huggingface/transformers'
import type { STTEngine, STTOptions, STTResult } from '../types'
import { modelManager } from '../infrastructure/modelManager'

class WhisperEngineImpl implements STTEngine {
  readonly id = 'whisper-tiny'
  readonly name = 'Whisper Tiny'
  readonly modelSize = 31_000_000
  readonly languages = ['en']

  private pipe: AutomaticSpeechRecognitionPipeline | null = null

  async init(device: 'webgpu' | 'wasm'): Promise<void> {
    // q8 quantisation requires WebGPU; WASM needs fp32 or q4
    const dtype = device === 'webgpu' ? 'q8' : 'fp32'
    this.pipe = await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
      device,
      dtype,
    })
    await modelManager.markDownloaded('whisper-tiny')
  }

  async transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult> {
    if (!this.pipe) throw new Error('WhisperEngine not initialised')
    const result = await this.pipe(audio, {
      language: options?.language ?? 'en',
      return_timestamps: true,
    })
    const output = result as { text: string; chunks?: Array<{ text: string; timestamp: [number, number] }> }
    return {
      text: output.text.trim(),
      language: options?.language ?? 'en',
      segments: output.chunks?.map((c) => ({ text: c.text, start: c.timestamp[0], end: c.timestamp[1] })),
    }
  }

  async dispose(): Promise<void> { this.pipe = null }
  isReady(): boolean { return this.pipe !== null }
}

export const whisperEngine = new WhisperEngineImpl()
