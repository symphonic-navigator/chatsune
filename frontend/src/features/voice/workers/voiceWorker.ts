/**
 * Voice inference Web Worker.
 *
 * Runs Whisper (STT) and Kokoro (TTS) off the main thread so the UI
 * stays responsive during inference. Device + dtype selection is done
 * inside the worker via a capability-aware ladder; the client only asks
 * for "init stt" / "init tts" and receives the resolved tuple back.
 */
import {
  pipeline,
  env,
  type AutomaticSpeechRecognitionPipeline,
} from '@huggingface/transformers'
import { KokoroTTS } from 'kokoro-js'
import {
  WHISPER_LADDER,
  KOKORO_LADDER,
  filterLadder,
  type DtypeEntry,
} from '../infrastructure/dtypeLadder'
import {
  probeCapabilities,
  computeFingerprint,
} from '../infrastructure/capabilityProbe'
import { getDecision, putDecision } from '../infrastructure/dtypeCache'
import { walkLadder, type WalkResult } from './voiceLadderRunner'

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

// ── WebGPU uncaptured-error capture ──
//
// ORT's JSEP backend holds a single shared GPUDevice across sessions.
// We hook its `uncapturederror` event each time we try a webgpu step
// so validation errors raised during load/warmup surface as a failure.

interface GpuErrorCapture {
  errors: string[]
  detach: () => void
}

function attachGpuErrorListener(): GpuErrorCapture {
  const ortEnv = env as unknown as { webgpu?: { device?: GPUDevice | null } }
  const device = ortEnv.webgpu?.device ?? null
  const errors: string[] = []
  if (!device) {
    return { errors, detach: () => {} }
  }
  const handler = (evt: Event) => {
    const ge = evt as unknown as { error: { message: string } }
    errors.push(ge.error?.message ?? 'unknown WebGPU error')
  }
  device.addEventListener('uncapturederror', handler as EventListener)
  return {
    errors,
    detach: () => device.removeEventListener('uncapturederror', handler as EventListener),
  }
}

// ── Ladder-driven init ──

async function resolveAndLoadWhisper(): Promise<{
  pipe: AutomaticSpeechRecognitionPipeline
  entry: DtypeEntry
  fromCache: boolean
}> {
  const caps = await probeCapabilities()
  const fp = computeFingerprint(caps)
  log('whisper: capabilities=%o fingerprint=%s', caps, fp)

  const cached = await getDecision('whisper', fp)
  if (cached) {
    log('whisper: cache HIT → %s/%s, loading...', cached.device, cached.dtype)
    try {
      const pipe = await loadWhisper(cached as unknown as DtypeEntry)
      await warmupWhisper(pipe)
      log('whisper: LOADED device=%s dtype=%s (fromCache=true)', cached.device, cached.dtype)
      return { pipe, entry: cached as unknown as DtypeEntry, fromCache: true }
    } catch (err) {
      log('whisper: cache hit failed (%s), falling through to ladder', String(err))
    }
  } else {
    log('whisper: cache MISS, walking ladder')
  }

  const ladder = filterLadder(WHISPER_LADDER, caps)
  let capture: GpuErrorCapture | null = null
  const result: WalkResult<AutomaticSpeechRecognitionPipeline> = await walkLadder({
    ladder,
    load: async (entry) => {
      capture?.detach()
      capture = entry.device === 'webgpu' ? attachGpuErrorListener() : { errors: [], detach: () => {} }
      return loadWhisper(entry)
    },
    warmup: async (_entry, pipe) => { await warmupWhisper(pipe) },
    collectGpuErrors: async () => {
      await new Promise<void>((r) => setTimeout(r, 0))
      const errs = capture?.errors.slice() ?? []
      capture?.detach()
      capture = null
      return errs
    },
    log: (line) => log('whisper: %s', line),
  })

  if (!result.ok) {
    throw new Error(`whisper: every ladder step failed — ${JSON.stringify(result.attempts)}`)
  }

  await putDecision('whisper', fp, { device: result.entry.device, dtype: result.entry.dtype })
  log('whisper: LOADED device=%s dtype=%s (fromCache=false)', result.entry.device, result.entry.dtype)
  return { pipe: result.model, entry: result.entry, fromCache: false }
}

async function loadWhisper(entry: DtypeEntry): Promise<AutomaticSpeechRecognitionPipeline> {
  return await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
    device: entry.device,
    dtype: entry.dtype,
  }) as AutomaticSpeechRecognitionPipeline
}

async function warmupWhisper(pipe: AutomaticSpeechRecognitionPipeline): Promise<void> {
  // 1 second of silence at 16 kHz
  const silence = new Float32Array(16_000)
  await pipe(silence, { language: 'en', return_timestamps: false })
}

async function resolveAndLoadKokoro(): Promise<{
  tts: KokoroTTS
  entry: DtypeEntry
  fromCache: boolean
}> {
  const caps = await probeCapabilities()
  const fp = computeFingerprint(caps)
  log('kokoro: capabilities=%o fingerprint=%s', caps, fp)

  const cached = await getDecision('kokoro', fp)
  if (cached) {
    log('kokoro: cache HIT → %s/%s, loading...', cached.device, cached.dtype)
    try {
      const ttsInst = await loadKokoro(cached as unknown as DtypeEntry)
      await warmupKokoro(ttsInst)
      log('kokoro: LOADED device=%s dtype=%s (fromCache=true)', cached.device, cached.dtype)
      return { tts: ttsInst, entry: cached as unknown as DtypeEntry, fromCache: true }
    } catch (err) {
      log('kokoro: cache hit failed (%s), falling through to ladder', String(err))
    }
  } else {
    log('kokoro: cache MISS, walking ladder')
  }

  const ladder = filterLadder(KOKORO_LADDER, caps)
  let capture: GpuErrorCapture | null = null
  const result: WalkResult<KokoroTTS> = await walkLadder({
    ladder,
    load: async (entry) => {
      capture?.detach()
      capture = entry.device === 'webgpu' ? attachGpuErrorListener() : { errors: [], detach: () => {} }
      return loadKokoro(entry)
    },
    warmup: async (_entry, inst) => { await warmupKokoro(inst) },
    collectGpuErrors: async () => {
      await new Promise<void>((r) => setTimeout(r, 0))
      const errs = capture?.errors.slice() ?? []
      capture?.detach()
      capture = null
      return errs
    },
    log: (line) => log('kokoro: %s', line),
  })

  if (!result.ok) {
    throw new Error(`kokoro: every ladder step failed — ${JSON.stringify(result.attempts)}`)
  }

  await putDecision('kokoro', fp, { device: result.entry.device, dtype: result.entry.dtype })
  log('kokoro: LOADED device=%s dtype=%s (fromCache=false)', result.entry.device, result.entry.dtype)
  return { tts: result.model, entry: result.entry, fromCache: false }
}

async function loadKokoro(entry: DtypeEntry): Promise<KokoroTTS> {
  return KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
    device: entry.device,
    dtype: entry.dtype as 'fp32' | 'fp16' | 'q8' | 'q4' | 'q4f16',
  })
}

async function warmupKokoro(inst: KokoroTTS): Promise<void> {
  const result = await inst.generate('test', {
    voice: 'af_heart' as NonNullable<Parameters<typeof inst.generate>[1]>['voice'],
  })
  // Some (device, dtype) combinations load and run without throwing but
  // produce numerically broken audio. Three failure modes seen so far on
  // browser WebGPU for Kokoro:
  //   - all-NaN buffer (fp16 overflow in some op)
  //   - all-zero buffer (silent, nothing rendered)
  //   - wildly scaled buffer (peak ≫ 1.0, hard-clips to a square wave —
  //     observed at peak ≈ 1.5e8 with fp32 on AMD RDNA-3)
  // Float32 PCM physically belongs in [-1, 1]; allow modest headroom
  // (PEAK_LIMIT) for normal output and reject anything beyond.
  const PEAK_LIMIT = 2.0
  const audio = (result as { audio: unknown }).audio
  if (!(audio instanceof Float32Array)) {
    throw new Error(`warmup: unexpected audio type ${Object.prototype.toString.call(audio)}`)
  }
  const probeLen = Math.min(audio.length, 2048)
  let hasUsableSample = false
  let peak = 0
  for (let i = 0; i < probeLen; i++) {
    const v = audio[i]!
    if (!Number.isFinite(v)) {
      throw new Error(`warmup produced non-finite sample at index ${i} (len=${audio.length})`)
    }
    const abs = Math.abs(v)
    if (abs > peak) peak = abs
    if (v !== 0) hasUsableSample = true
  }
  if (!hasUsableSample) {
    throw new Error(`warmup produced silent audio (len=${audio.length})`)
  }
  if (peak > PEAK_LIMIT) {
    throw new Error(`warmup produced clipped audio: peak=${peak} > ${PEAK_LIMIT} (len=${audio.length})`)
  }
}

// ── Message handling ──

self.onmessage = async (e: MessageEvent) => {
  const msg = e.data

  switch (msg.type) {
    case 'init-stt': {
      log('init-stt start')
      try {
        const { pipe, entry, fromCache } = await resolveAndLoadWhisper()
        sttPipe = pipe
        self.postMessage({
          type: 'init-stt-done',
          resolved: { device: entry.device, dtype: entry.dtype, fromCache },
        })
      } catch (err) {
        log('init-stt error:', err)
        self.postMessage({ type: 'init-stt-error', error: String(err) })
      }
      break
    }

    case 'init-tts': {
      log('init-tts start')
      try {
        const { tts: inst, entry, fromCache } = await resolveAndLoadKokoro()
        tts = inst
        self.postMessage({
          type: 'init-tts-done',
          voices: KOKORO_VOICES,
          resolved: { device: entry.device, dtype: entry.dtype, fromCache },
        })
      } catch (err) {
        log('init-tts error:', err)
        self.postMessage({ type: 'init-tts-error', error: String(err) })
      }
      break
    }

    case 'transcribe': {
      log('transcribe start, id=%s, audioLen=%d', msg.id, msg.audio?.length ?? 0)
      if (!sttPipe) {
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
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: 'TTS not initialised' })
        break
      }
      try {
        const t0 = performance.now()
        const result = await tts.generate(msg.text, {
          voice: msg.voiceId as NonNullable<Parameters<typeof tts.generate>[1]>['voice'],
        })
        // Diagnostic: verify the audio payload is a real signal, not silence
        // or a chunked structure misread as a single Float32Array.
        const rawAudio: unknown = (result as { audio: unknown }).audio
        const isFloat32 = rawAudio instanceof Float32Array
        const isArray = Array.isArray(rawAudio)
        log('synthesise diag: rawType=%s isFloat32=%s isArray=%s sampling_rate=%o',
            Object.prototype.toString.call(rawAudio), isFloat32, isArray,
            (result as { sampling_rate?: number }).sampling_rate)
        const audio = result.audio as unknown as Float32Array
        const elapsed = Math.round(performance.now() - t0)
        let max = 0
        for (let i = 0; i < audio.length; i++) {
          const v = Math.abs(audio[i] ?? 0)
          if (v > max) max = v
        }
        log('synthesise done, id=%s, %dms, audioLen=%d, max=%f, first10=%o',
            msg.id, elapsed, audio.length, max, Array.from(audio.slice(0, 10)))
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
