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
  private muted = false
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false
  private streamClosed = false
  private pendingGapTimer: ReturnType<typeof setTimeout> | null = null
  // ctx.currentTime recorded when the current source's start(when, offset)
  // was scheduled, adjusted for offset so
  //   ctx.currentTime - currentSourceStartSec
  // gives elapsed playback within the *buffer* (not since the call).
  private currentSourceStartSec = 0
  // Position within mutedEntry.audio at which mute() captured the pause.
  // Consumed once on the next resumeFromMute() and then cleared.
  private mutedOffsetSec = 0
  // One-shot flag: if non-null, the next playNext() starts its source at this
  // offset (seconds into the buffer). Cleared as soon as it's consumed.
  private pendingResumeOffsetSec: number | null = null
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

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null && !this.muted) this.playNext()
    this.emit()
  }

  closeStream(): void {
    this.streamClosed = true
    if (!this.playing && this.queue.length === 0 && this.pendingGapTimer === null && !this.muted) {
      this.callbacks?.onFinished()
    }
  }

  stopAll(): void {
    this.queue = []
    this.streamClosed = false
    this.mutedEntry = null
    this.muted = false
    this.mutedOffsetSec = 0
    this.pendingResumeOffsetSec = null
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
    this.emit()
  }

  /**
   * Non-destructive pause used by Tentative Barge. Stops the current source
   * (if any), captures the elapsed playback position, and remembers the entry
   * so resumeFromMute() can continue from that exact offset rather than
   * restarting the segment. Also cancels any pending gap timer so a mute that
   * arrives between segments still inhibits playback. The queue and
   * streamClosed flag are preserved. Idempotent.
   */
  mute(): void {
    if (this.muted) return // already muted
    // Cancel any scheduled next-segment play first — it runs independently
    // of currentSource and would otherwise bypass the mute when no source
    // is currently playing (between-segments case).
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource && this.currentEntry) {
      // Record the position within the current buffer so resumeFromMute() can
      // continue from there. Cap just under the segment's effective audio
      // length to avoid resuming inside the modulation tail padding.
      const elapsed = Math.max(0, (this.ctx?.currentTime ?? 0) - this.currentSourceStartSec)
      const segmentDur = this.currentEntry.audio.length / SAMPLE_RATE
      this.mutedOffsetSec = Math.min(elapsed, Math.max(0, segmentDur - 0.01))
      this.mutedEntry = this.currentEntry
      this.currentSource.onended = null // don't advance the queue
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
      this.currentEntry = null
      this.playing = false
      this.muted = true
      this.emit()
      return
    }
    // Nothing playing right now. Still mark as muted if a gap timer was
    // pending — that means a segment was about to start and we must block
    // it. If neither a source NOR a gap timer was active, mute is a no-op.
    // We detect "gap timer was pending" by whether the queue is non-empty
    // (the gap timer would have been scheduled only because playNext was
    // going to dequeue the next entry).
    if (this.queue.length > 0) {
      this.playing = false
      this.muted = true
      this.emit()
    }
  }

  /**
   * Resume after a mute(). Re-queues the muted entry at the head of the
   * queue and kicks playback, continuing from the exact offset captured by
   * the preceding mute() rather than replaying the segment from the start.
   * If there is no mutedEntry (mute was called between segments), simply
   * restart playNext so the next queued entry plays from its own start.
   * No-op if not muted.
   */
  resumeFromMute(): void {
    if (!this.muted) return
    const entry = this.mutedEntry
    const offsetSec = this.mutedOffsetSec
    this.mutedEntry = null
    this.mutedOffsetSec = 0
    this.muted = false
    if (entry !== null) {
      this.queue.unshift(entry)
      this.pendingResumeOffsetSec = offsetSec
    }
    if (!this.playing && this.pendingGapTimer === null) this.playNext()
    this.emit()
  }

  /**
   * Skip-past-muted escape hatch for the tentative-barge feedback-loop
   * guard. Drops the muted entry without replaying it and lets the queue
   * continue. Unlike resumeFromMute() (which continues from the captured
   * offset) and stopAll() (which cancels the whole session), this preserves
   * the rest of the queue and the streamClosed flag.
   */
  discardMuted(): void {
    if (!this.muted) return
    this.mutedEntry = null
    this.mutedOffsetSec = 0
    this.pendingResumeOffsetSec = null
    this.muted = false
    if (this.queue.length > 0 && !this.playing && this.pendingGapTimer === null) {
      this.playNext()
    }
    this.emit()
  }

  isMuted(): boolean { return this.muted }

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
      this.emit()
      return
    }

    this.playing = true
    this.currentEntry = entry
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

      source.onended = () => {
        this.currentSource = null
        this.currentEntry = null
        if (modNode) {
          try { modNode.disconnect() } catch { /* ignore */ }
        }
        this.emit()
        this.scheduleNext()
      }

      const offset = this.pendingResumeOffsetSec ?? 0
      this.pendingResumeOffsetSec = null
      // Keep the invariant ctx.currentTime - currentSourceStartSec == elapsed
      // within buffer, even when skipping the first `offset` seconds.
      this.currentSourceStartSec = this.ctx.currentTime - offset
      source.start(0, offset)
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
