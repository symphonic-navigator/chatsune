/**
 * Voice inference Web Worker.
 *
 * Runs Whisper (STT) and Kokoro (TTS) off the main thread so the UI
 * stays responsive during inference. Communicates via postMessage.
 */
import { pipeline, type AutomaticSpeechRecognitionPipeline } from '@huggingface/transformers'
import { KokoroTTS } from 'kokoro-js'

// ── State ──

let sttPipe: AutomaticSpeechRecognitionPipeline | null = null
let tts: KokoroTTS | null = null

// ── Voice presets (must match kokoroEngine.ts) ──

const KOKORO_VOICES = [
  { id: 'af_heart', name: 'Heart (Female)', language: 'en', gender: 'female' },
  { id: 'af_bella', name: 'Bella (Female)', language: 'en', gender: 'female' },
  { id: 'af_sarah', name: 'Sarah (Female)', language: 'en', gender: 'female' },
  { id: 'af_nicole', name: 'Nicole (Female)', language: 'en', gender: 'female' },
  { id: 'af_sky', name: 'Sky (Female)', language: 'en', gender: 'female' },
  { id: 'am_adam', name: 'Adam (Male)', language: 'en', gender: 'male' },
  { id: 'am_michael', name: 'Michael (Male)', language: 'en', gender: 'male' },
  { id: 'bf_emma', name: 'Emma (British F)', language: 'en', gender: 'female' },
  { id: 'bf_isabella', name: 'Isabella (British F)', language: 'en', gender: 'female' },
  { id: 'bm_george', name: 'George (British M)', language: 'en', gender: 'male' },
  { id: 'bm_lewis', name: 'Lewis (British M)', language: 'en', gender: 'male' },
] as const

// ── Message handling ──

self.onmessage = async (e: MessageEvent) => {
  const msg = e.data

  switch (msg.type) {
    case 'init-stt': {
      try {
        const dtype = msg.device === 'webgpu' ? 'q8' : 'fp32'
        sttPipe = await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
          device: msg.device,
          dtype,
        }) as AutomaticSpeechRecognitionPipeline
        self.postMessage({ type: 'init-stt-done' })
      } catch (err) {
        self.postMessage({ type: 'init-stt-error', error: String(err) })
      }
      break
    }

    case 'init-tts': {
      try {
        tts = await KokoroTTS.from_pretrained(
          'onnx-community/Kokoro-82M-v1.0-ONNX',
          { dtype: msg.device === 'webgpu' ? 'fp32' : 'fp32' },
        )
        self.postMessage({ type: 'init-tts-done', voices: KOKORO_VOICES })
      } catch (err) {
        self.postMessage({ type: 'init-tts-error', error: String(err) })
      }
      break
    }

    case 'transcribe': {
      if (!sttPipe) {
        self.postMessage({ type: 'transcribe-error', id: msg.id, error: 'STT not initialised' })
        break
      }
      try {
        const result = await sttPipe(msg.audio, {
          language: msg.language ?? 'en',
          return_timestamps: true,
        })
        const output = result as { text: string; chunks?: Array<{ text: string; timestamp: [number, number] }> }
        self.postMessage({
          type: 'transcribe-done',
          id: msg.id,
          text: output.text.trim(),
          language: msg.language ?? 'en',
          segments: output.chunks?.map((c) => ({ text: c.text, start: c.timestamp[0], end: c.timestamp[1] })),
        })
      } catch (err) {
        self.postMessage({ type: 'transcribe-error', id: msg.id, error: String(err) })
      }
      break
    }

    case 'synthesise': {
      if (!tts) {
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: 'TTS not initialised' })
        break
      }
      try {
        const result = await tts.generate(msg.text, { voice: msg.voiceId as Parameters<typeof tts.generate>[1]['voice'] })
        const audio = result.audio as unknown as Float32Array
        // Transfer the buffer for zero-copy performance
        self.postMessage(
          { type: 'synthesise-done', id: msg.id, audio },
          { transfer: [audio.buffer] },
        )
      } catch (err) {
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: String(err) })
      }
      break
    }
  }
}
