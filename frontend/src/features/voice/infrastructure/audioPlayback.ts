import type { SpeechSegment } from '../types'

interface QueueEntry { audio: Float32Array; segment: SpeechSegment }

export interface AudioPlaybackCallbacks {
  onSegmentStart: (segment: SpeechSegment) => void
  onFinished: () => void
}

class AudioPlaybackImpl {
  private queue: QueueEntry[] = []
  private ctx: AudioContext | null = null
  private currentSource: AudioBufferSourceNode | null = null
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false

  setCallbacks(callbacks: AudioPlaybackCallbacks): void { this.callbacks = callbacks }

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing) this.playNext()
  }

  stopAll(): void {
    this.queue = []
    if (this.currentSource) {
      this.currentSource.onended = null // prevent stale onended → playNext → onFinished
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.playing = false
  }

  skipCurrent(): void {
    if (this.currentSource) {
      // Keep onended intact — it calls playNext for the next segment
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
  }

  private async playNext(): Promise<void> {
    const entry = this.queue.shift()
    if (!entry) {
      this.playing = false
      this.callbacks?.onFinished()
      return
    }

    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)

    try {
      if (!this.ctx || this.ctx.state === 'closed') {
        this.ctx = new AudioContext({ sampleRate: 24_000 })
      }

      // Resume suspended AudioContext (browser policy: needs user gesture)
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
        this.playNext()
      }

      source.start()
    } catch (err) {
      console.error('[AudioPlayback] Failed to play segment:', err)
      this.currentSource = null
      // Try next segment instead of getting permanently stuck
      this.playNext()
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
