import type { GroupChild } from '../../chat/responseTaskGroup'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'

export interface PlaybackChildOpts {
  correlationId: string
  gapMs: number
  onSegmentStart?: () => void
  onFinished?: () => void
  /** Origin of the synth chunks fed into this child. Stamped onto every
   *  inline-trigger event emitted from the audio pipeline so downstream
   *  consumers can distinguish active LLM streaming from re-triggered
   *  read-aloud playback. Defaults to `'live_stream'` for the existing
   *  voice-pipeline call sites until Phase 5 wires the explicit source. */
  streamSource?: 'live_stream' | 'read_aloud'
}

export function createPlaybackChild(opts: PlaybackChildOpts): GroupChild {
  const { correlationId, gapMs, onSegmentStart, onFinished } = opts
  const streamSource = opts.streamSource ?? 'live_stream'
  const prefix = `[playback ${correlationId.slice(0, 8)}]`
  let drainResolve: (() => void) | null = null

  audioPlayback.setCurrentToken(correlationId)
  audioPlayback.setCallbacks({
    gapMs,
    onSegmentStart: (seg) => {
      console.log(`[TTS-play ${correlationId.slice(0, 8)}] start "${seg.text.slice(0, 40)}"`)
      onSegmentStart?.()
    },
    onFinished: () => {
      console.log(`${prefix} finished`)
      onFinished?.()
      drainResolve?.()
      drainResolve = null
    },
    onInlineTrigger: (event) => {
      // Wrap the trigger payload in the standard BaseEvent envelope so the
      // shared frontend event bus dispatches it like any other typed event.
      // Sequence is unused for purely client-emitted events; stamp something
      // monotonic-ish so it cannot be confused with a real backend stream.
      eventBus.emit({
        id: `inline-trig-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        type: Topics.INTEGRATION_INLINE_TRIGGER,
        sequence: '0',
        scope: 'frontend',
        correlation_id: event.correlation_id || correlationId,
        timestamp: event.timestamp,
        payload: { ...event, source: streamSource },
      })
    },
  })

  return {
    name: 'playback',

    onDelta(): void {},

    onStreamEnd(_token): Promise<void> {
      return new Promise<void>((resolve) => {
        drainResolve = resolve
        audioPlayback.closeStream()
      })
    },

    onCancel(_reason, token): void {
      if (token !== correlationId) return
      audioPlayback.clearScope(correlationId)   // first, while token still matches
      audioPlayback.setCurrentToken(null)        // then null out the token
      drainResolve?.()
      drainResolve = null
    },

    onPause(): void {
      audioPlayback.pause()
    },
    onResume(): void {
      audioPlayback.resume()
    },

    teardown(): void {
      audioPlayback.setCurrentToken(null)
    },
  }
}
