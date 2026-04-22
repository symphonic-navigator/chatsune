import type { SpeechSegment } from '../types'
import { ensureSoundTouchReady, createModulationNode } from './soundTouchLoader'

const SAMPLE_RATE = 24_000
// SoundTouch has internal latency and, when speed > 1, the source ends before
// the worklet has flushed its buffered output — producing a clipped tail.
// Pad each modulated buffer with a short silence so the worklet has room to
// drain. Only applied when modulation is active to avoid gaps at speed = 1.
const MODULATION_TAIL_SAMPLES = Math.round((SAMPLE_RATE * 150) / 1000) // 150 ms

interface QueueEntry { audio: Float32Array; segment: SpeechSegment }

export interface AudioPlaybackCallbacks {
  gapMs?: number
  onSegmentStart: (segment: SpeechSegment) => void
  onFinished: () => void
}

class AudioPlaybackImpl {
  private queue: QueueEntry[] = []
  private ctx: AudioContext | null = null
  private currentSource: AudioBufferSourceNode | null = null
  private currentToken: string | null = null
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false
  private streamClosed = false
  private pendingGapTimer: ReturnType<typeof setTimeout> | null = null
  // Listeners observing playing-state changes. Used by the React hook so
  // components can reflect live browser audio state without polling.
  private listeners = new Set<() => void>()

  setCallbacks(callbacks: AudioPlaybackCallbacks): void { this.callbacks = callbacks }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private emit(): void {
    for (const listener of this.listeners) {
      try { listener() } catch (err) {
        console.error('[AudioPlayback] Listener threw:', err)
      }
    }
  }

  setCurrentToken(token: string | null): void {
    this.currentToken = token
  }

  /**
   * Drops the queue and stops the current source if `token` matches the
   * active scope token. No-op when the tokens differ.
   */
  clearScope(token: string): void {
    if (this.currentToken !== token) return
    this.queue = []
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource) {
      this.currentSource.onended = null
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.playing = false
    this.emit()
  }

  enqueue(audio: Float32Array, segment: SpeechSegment, token?: string): void {
    // When a token is supplied and a current scope token is set, drop the chunk
    // if they do not match. Callers that pass no token are always accepted
    // (non-Group call sites such as ReadAloud and PersonaVoiceConfig preview).
    if (token !== undefined && this.currentToken !== null && token !== this.currentToken) {
      console.debug(`[audioPlayback] drop chunk (token mismatch: got=${token}, current=${this.currentToken})`)
      return
    }
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null) this.playNext()
    this.emit()
  }

  closeStream(): void {
    this.streamClosed = true
    if (!this.playing && this.queue.length === 0 && this.pendingGapTimer === null) {
      this.callbacks?.onFinished()
    }
  }

  stopAll(): void {
    this.queue = []
    this.streamClosed = false
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource) {
      this.currentSource.onended = null // prevent stale onended → playNext → onFinished
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.playing = false
    this.emit()
  }

  private scheduleNext(): void {
    const gap = this.callbacks?.gapMs ?? 0
    if (gap > 0) {
      this.pendingGapTimer = setTimeout(() => {
        this.pendingGapTimer = null
        this.playNext()
      }, gap)
    } else {
      this.playNext()
    }
  }

  private async playNext(): Promise<void> {
    const entry = this.queue.shift()
    if (!entry) {
      this.playing = false
      if (this.streamClosed) this.callbacks?.onFinished()
      this.emit()
      return
    }

    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)
    this.emit()

    try {
      if (!this.ctx || this.ctx.state === 'closed') {
        this.ctx = new AudioContext({ sampleRate: 24_000 })
      }
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume()
      }

      const speed = entry.segment.speed ?? 1.0
      const pitch = entry.segment.pitch ?? 0
      const needsModulation = speed !== 1.0 || pitch !== 0

      const bufferLength = needsModulation
        ? entry.audio.length + MODULATION_TAIL_SAMPLES
        : entry.audio.length
      const buffer = this.ctx.createBuffer(1, bufferLength, SAMPLE_RATE)
      // createBuffer zeroes the channel data, so the tail is silence already.
      buffer.getChannelData(0).set(entry.audio)

      const source = this.ctx.createBufferSource()
      source.buffer = buffer

      let modNode: AudioNode | null = null
      if (needsModulation) {
        const ready = await ensureSoundTouchReady(this.ctx)
        if (ready) {
          modNode = createModulationNode(this.ctx, speed, pitch)
        }
      }

      if (modNode) {
        // Drive tempo via the source's playbackRate; SoundTouch's playbackRate
        // param tells the processor about that rate so it can compensate the
        // resulting pitch change. stNode.tempo alone produces stuttering at
        // 128-sample worklet quanta (see soundTouchLoader comment).
        source.playbackRate.value = speed
        source.connect(modNode)
        modNode.connect(this.ctx.destination)
      } else {
        source.connect(this.ctx.destination)
      }

      this.currentSource = source

      // Diagnostic log — remove once the "TTS starts only at end of
      // inference" bug is understood. Track segments through playback.
      const preview = entry.segment.text.slice(0, 40).replace(/\s+/g, ' ')

      source.onended = () => {
        this.currentSource = null
        if (modNode) {
          try { modNode.disconnect() } catch { /* ignore */ }
        }
        console.log(`[TTS-play]  done  "${preview}"`)
        this.emit()
        this.scheduleNext()
      }

      source.start(0, 0)
      console.log(`[TTS-play]  start "${preview}"`)
    } catch (err) {
      console.error('[AudioPlayback] Failed to play segment:', err)
      this.currentSource = null
      this.scheduleNext()
    }
  }

  isPlaying(): boolean { return this.playing }

  dispose(): void {
    this.stopAll()
    if (this.ctx && this.ctx.state !== 'closed') {
      this.ctx.close()
    }
    this.ctx = null
    this.callbacks = null
  }
}

export const audioPlayback = new AudioPlaybackImpl()
