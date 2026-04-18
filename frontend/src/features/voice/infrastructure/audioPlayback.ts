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
  private currentEntry: QueueEntry | null = null
  private mutedEntry: QueueEntry | null = null
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false
  private streamClosed = false
  private pendingGapTimer: ReturnType<typeof setTimeout> | null = null

  setCallbacks(callbacks: AudioPlaybackCallbacks): void { this.callbacks = callbacks }

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null && this.mutedEntry === null) this.playNext()
  }

  closeStream(): void {
    this.streamClosed = true
    if (!this.playing && this.queue.length === 0 && this.pendingGapTimer === null && this.mutedEntry === null) {
      this.callbacks?.onFinished()
    }
  }

  stopAll(): void {
    this.queue = []
    this.streamClosed = false
    this.mutedEntry = null
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource) {
      this.currentSource.onended = null // prevent stale onended → playNext → onFinished
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.currentEntry = null
    this.playing = false
  }

  /**
   * Non-destructive pause used by Tentative Barge. Stops the current source
   * and remembers its entry so resumeFromMute() can replay it from the
   * start. The queue and streamClosed flag are preserved. Idempotent.
   */
  mute(): void {
    if (this.mutedEntry !== null) return // already muted
    if (!this.currentSource || !this.currentEntry) return // nothing to mute
    this.mutedEntry = this.currentEntry
    this.currentSource.onended = null // don't advance the queue
    try { this.currentSource.stop() } catch { /* already stopped */ }
    this.currentSource = null
    this.currentEntry = null
    this.playing = false
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
  }

  /**
   * Resume after a mute(). Re-queues the muted entry at the head of the
   * queue and kicks playback. No-op if nothing is muted.
   */
  resumeFromMute(): void {
    const entry = this.mutedEntry
    if (!entry) return
    this.mutedEntry = null
    this.queue.unshift(entry)
    if (!this.playing && this.pendingGapTimer === null) this.playNext()
  }

  isMuted(): boolean { return this.mutedEntry !== null }

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
      this.currentEntry = null
      if (this.streamClosed) this.callbacks?.onFinished()
      return
    }

    this.playing = true
    this.currentEntry = entry
    this.callbacks?.onSegmentStart(entry.segment)

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

      source.onended = () => {
        this.currentSource = null
        this.currentEntry = null
        if (modNode) {
          try { modNode.disconnect() } catch { /* ignore */ }
        }
        this.scheduleNext()
      }

      source.start()
    } catch (err) {
      console.error('[AudioPlayback] Failed to play segment:', err)
      this.currentSource = null
      this.currentEntry = null
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
