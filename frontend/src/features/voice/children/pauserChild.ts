import type { GroupChild } from '../../chat/responseTaskGroup'
import type { SpeechSegment } from '../types'

export interface PauserChildOpts {
  correlationId: string
  /**
   * Called when the pauser has decided a pause is finished and the next
   * segment is cleared for synth/playback. For the initial implementation
   * this is pass-through — the pauser just forwards every segment.
   * Future enhancement: insert silence buffers between segments here.
   */
  onSegmentReleased: (segment: SpeechSegment, token: string) => void
}

export function createPauserChild(opts: PauserChildOpts): GroupChild & {
  pushSegment: (segment: SpeechSegment, token: string) => void
} {
  const { correlationId, onSegmentReleased } = opts

  return {
    name: 'pauser',

    pushSegment(segment: SpeechSegment, token: string): void {
      if (token !== correlationId) return
      onSegmentReleased(segment, token)
    },

    onDelta(): void { /* pauser reacts to segments, not raw deltas */ },
    onStreamEnd(): void {},
    onCancel(): void {},
    teardown(): void {},
  }
}
