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
    this.currentSource?.stop()
    this.currentSource = null
    this.playing = false
  }

  skipCurrent(): void {
    this.currentSource?.stop()
    this.currentSource = null
    // playNext will be called by the onended handler
  }

  private playNext(): void {
    const entry = this.queue.shift()
    if (!entry) { this.playing = false; this.callbacks?.onFinished(); return }
    this.playing = true
    this.callbacks?.onSegmentStart(entry.segment)
    if (!this.ctx) this.ctx = new AudioContext()
    const buffer = this.ctx.createBuffer(1, entry.audio.length, 24_000)
    buffer.getChannelData(0).set(entry.audio)
    const source = this.ctx.createBufferSource()
    source.buffer = buffer
    source.connect(this.ctx.destination)
    this.currentSource = source
    source.onended = () => { this.currentSource = null; this.playNext() }
    source.start()
  }

  isPlaying(): boolean { return this.playing }

  dispose(): void { this.stopAll(); this.ctx?.close(); this.ctx = null; this.callbacks = null }
}

export const audioPlayback = new AudioPlaybackImpl()
