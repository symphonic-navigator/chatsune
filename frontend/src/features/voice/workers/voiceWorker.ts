/**
 * Voice inference Web Worker.
 *
 * Runs Whisper (STT) and Kokoro (TTS) off the main thread so the UI
 * stays responsive during inference. Communicates via postMessage.
 */
import { pipeline, type AutomaticSpeechRecognitionPipeline } from '@huggingface/transformers'
import { KokoroTTS } from 'kokoro-js'

const log = (msg: string, ...args: unknown[]) => console.log(`[VoiceWorker] ${msg}`, ...args)

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
      log('init-stt start, device=%s', msg.device)
      try {
        const dtype = msg.device === 'webgpu' ? 'q8' : 'fp32'
        sttPipe = await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
          device: msg.device,
          dtype,
        }) as AutomaticSpeechRecognitionPipeline
        log('init-stt done')
        self.postMessage({ type: 'init-stt-done' })
      } catch (err) {
        log('init-stt error:', err)
        self.postMessage({ type: 'init-stt-error', error: String(err) })
      }
      break
    }

    case 'init-tts': {
      log('init-tts start, device=%s', msg.device)
      try {
        tts = await KokoroTTS.from_pretrained(
          'onnx-community/Kokoro-82M-v1.0-ONNX',
          { dtype: msg.device === 'webgpu' ? 'fp32' : 'fp32' },
        )
        log('init-tts done')
        self.postMessage({ type: 'init-tts-done', voices: KOKORO_VOICES })
      } catch (err) {
        log('init-tts error:', err)
        self.postMessage({ type: 'init-tts-error', error: String(err) })
      }
      break
    }

    case 'transcribe': {
      log('transcribe start, id=%s, audioLen=%d', msg.id, msg.audio?.length ?? 0)
      if (!sttPipe) {
        log('transcribe error: STT not initialised')
        self.postMessage({ type: 'transcribe-error', id: msg.id, error: 'STT not initialised' })
        break
      }
      try {
        const t0 = performance.now()
        const result = await sttPipe(msg.audio, {
          language: msg.language ?? 'en',
          return_timestamps: true,
        })
        const elapsed = Math.round(performance.now() - t0)
        const output = result as { text: string; chunks?: Array<{ text: string; timestamp: [number, number] }> }
        log('transcribe done, id=%s, %dms, text="%s"', msg.id, elapsed, output.text.trim().slice(0, 60))
        self.postMessage({
          type: 'transcribe-done',
          id: msg.id,
          text: output.text.trim(),
          language: msg.language ?? 'en',
          segments: output.chunks?.map((c) => ({ text: c.text, start: c.timestamp[0], end: c.timestamp[1] })),
        })
      } catch (err) {
        log('transcribe error, id=%s:', msg.id, err)
        self.postMessage({ type: 'transcribe-error', id: msg.id, error: String(err) })
      }
      break
    }

    case 'synthesise': {
      log('synthesise start, id=%s, text="%s", voice=%s', msg.id, msg.text.slice(0, 40), msg.voiceId)
      if (!tts) {
        log('synthesise error: TTS not initialised')
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: 'TTS not initialised' })
        break
      }
      try {
        const t0 = performance.now()
        const result = await tts.generate(msg.text, { voice: msg.voiceId as NonNullable<Parameters<typeof tts.generate>[1]>['voice'] })
        const audio = result.audio as unknown as Float32Array
        const elapsed = Math.round(performance.now() - t0)
        log('synthesise done, id=%s, %dms, audioLen=%d', msg.id, elapsed, audio.length)
        self.postMessage(
          { type: 'synthesise-done', id: msg.id, audio },
          { transfer: [audio.buffer] },
        )
      } catch (err) {
        log('synthesise error, id=%s:', msg.id, err)
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: String(err) })
      }
      break
    }
  }
}
