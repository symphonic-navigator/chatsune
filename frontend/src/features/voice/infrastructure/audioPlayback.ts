import type { SpeechSegment } from '../types'

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
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false
  private streamClosed = false
  private pendingGapTimer: ReturnType<typeof setTimeout> | null = null

  setCallbacks(callbacks: AudioPlaybackCallbacks): void { this.callbacks = callbacks }

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null) this.playNext()
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
  }

  skipCurrent(): void {
    if (this.currentSource) {
      // Keep onended intact — it schedules the next segment.
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
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
      return
    }

    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)

    try {
      if (!this.ctx || this.ctx.state === 'closed') {
        this.ctx = new AudioContext({ sampleRate: 24_000 })
      }
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume()
      }

      const buffer = this.ctx.createBuffer(1, entry.audio.length, 24_000)
      buffer.getChannelData(0).set(entry.audio)

      const source = this.ctx.createBufferSource()
      source.buffer = buffer
      source.connect(this.ctx.destination)
      this.currentSource = source

      source.onended = () => {
        this.currentSource = null
        this.scheduleNext()
      }

      source.start()
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
