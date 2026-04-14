/**
 * Main-thread client for the voice inference Web Worker.
 *
 * Provides Promise-based methods that match the STTEngine/TTSEngine
 * interfaces. All heavy inference — including device + dtype selection —
 * runs in the worker. This class only passes messages and surfaces the
 * resolved `{ device, dtype, fromCache }` tuple back to callers.
 */
import type { VoicePreset } from '../types'

const log = (msg: string, ...args: unknown[]) => console.log(`[VoiceClient] ${msg}`, ...args)

type PendingResolve = { resolve: (value: unknown) => void; reject: (reason: unknown) => void }

export interface ResolvedDtype {
  device: 'webgpu' | 'wasm'
  dtype: string
  fromCache: boolean
}

export interface SttInitResult {
  resolved: ResolvedDtype
}

export interface TtsInitResult {
  voices: VoicePreset[]
  resolved: ResolvedDtype
}

class VoiceWorkerClient {
  private worker: Worker | null = null
  private pending = new Map<string, PendingResolve>()
  private nextId = 0
  private initCallbacks: Record<string, PendingResolve> = {}

  private getWorker(): Worker {
    if (!this.worker) {
      log('spawning worker')
      this.worker = new Worker(
        new URL('./voiceWorker.ts', import.meta.url),
        { type: 'module' },
      )
      this.worker.onmessage = (e) => this.handleMessage(e.data)
      this.worker.onerror = (e) => {
        console.error('[VoiceClient] Worker error:', e)
      }
    }
    return this.worker
  }

  private handleMessage(msg: Record<string, unknown>): void {
    switch (msg.type) {
      case 'init-stt-done': {
        const resolved = msg.resolved as ResolvedDtype | undefined
        log('init-stt-done: %o', resolved)
        this.initCallbacks['stt']?.resolve({ resolved: resolved! } satisfies SttInitResult)
        delete this.initCallbacks['stt']
        break
      }
      case 'init-stt-error':
        log('init-stt-error: %s', msg.error)
        this.initCallbacks['stt']?.reject(new Error(msg.error as string))
        delete this.initCallbacks['stt']
        break
      case 'init-tts-done': {
        const resolved = msg.resolved as ResolvedDtype | undefined
        log('init-tts-done: %o', resolved)
        this.initCallbacks['tts']?.resolve({
          voices: msg.voices as VoicePreset[],
          resolved: resolved!,
        } satisfies TtsInitResult)
        delete this.initCallbacks['tts']
        break
      }
      case 'init-tts-error':
        log('init-tts-error: %s', msg.error)
        this.initCallbacks['tts']?.reject(new Error(msg.error as string))
        delete this.initCallbacks['tts']
        break
      case 'transcribe-done':
      case 'transcribe-error':
      case 'synthesise-done':
      case 'synthesise-error': {
        const id = msg.id as string
        const p = this.pending.get(id)
        if (!p) {
          log('%s received for id=%s but no pending handler (cancelled?)', msg.type, id)
          break
        }
        this.pending.delete(id)
        if ((msg.type as string).endsWith('-error')) {
          log('%s id=%s: %s', msg.type, id, msg.error)
          p.reject(new Error(msg.error as string))
        } else {
          log('%s id=%s', msg.type, id)
          p.resolve(msg)
        }
        break
      }
    }
  }

  async initSTT(): Promise<SttInitResult> {
    log('initSTT()')
    const w = this.getWorker()
    return new Promise((resolve, reject) => {
      this.initCallbacks['stt'] = { resolve: resolve as (v: unknown) => void, reject }
      w.postMessage({ type: 'init-stt' })
    })
  }

  async initTTS(): Promise<TtsInitResult> {
    log('initTTS()')
    const w = this.getWorker()
    return new Promise((resolve, reject) => {
      this.initCallbacks['tts'] = { resolve: resolve as (v: unknown) => void, reject }
      w.postMessage({ type: 'init-tts' })
    })
  }

  async transcribe(audio: Float32Array, language?: string): Promise<{ text: string; language: string }> {
    const w = this.getWorker()
    const id = String(this.nextId++)
    log('transcribe request id=%s, audioLen=%d', id, audio.length)
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject })
      w.postMessage({ type: 'transcribe', id, audio, language }, { transfer: [audio.buffer] })
    })
  }

  async synthesise(text: string, voiceId: string): Promise<Float32Array> {
    const w = this.getWorker()
    const id = String(this.nextId++)
    log('synthesise request id=%s, text="%s", voice=%s', id, text.slice(0, 40), voiceId)
    return new Promise((resolve, reject) => {
      this.pending.set(id, {
        resolve: (msg) => resolve((msg as { audio: Float32Array }).audio),
        reject,
      })
      w.postMessage({ type: 'synthesise', id, text, voiceId })
    })
  }

  cancel(id: string): void {
    const p = this.pending.get(id)
    if (p) {
      log('cancel id=%s', id)
      this.pending.delete(id)
      p.reject(new Error('Cancelled'))
    }
  }

  cancelAll(): void {
    if (this.pending.size === 0) return
    log('cancelAll (%d pending)', this.pending.size)
    for (const [id, p] of this.pending) {
      p.reject(new Error('Cancelled'))
      this.pending.delete(id)
    }
  }

  dispose(): void {
    log('dispose')
    this.cancelAll()
    this.worker?.terminate()
    this.worker = null
  }
}

export const voiceWorker = new VoiceWorkerClient()
