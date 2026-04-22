import type { GroupChild, CancelReason } from '../../chat/responseTaskGroup'
import type { SpeechSegment } from '../types'
import type { StreamingSentencer } from '../pipeline/streamingSentencer'

export interface SentencerChildOpts {
  correlationId: string
  sentencer: StreamingSentencer
  /**
   * Voice-internal event fan-out: called whenever the sentencer emits a
   * segment, either from push() mid-stream or flush() at stream end.
   * Subscribers (pauser, synth) register via DI at createPauser/createSynth
   * time — see the children factory in ChatView.
   */
  onSegment: (segment: SpeechSegment, token: string) => void
}

export function createSentencerChild(opts: SentencerChildOpts): GroupChild {
  const { correlationId, sentencer, onSegment } = opts
  const prefix = `[sentencer ${correlationId.slice(0, 8)}]`

  return {
    name: 'sentencer',

    onDelta(delta: string, token: string): void {
      if (token !== correlationId) return
      const segments = sentencer.push(delta)
      for (const s of segments) onSegment(s, correlationId)
    },

    async onStreamEnd(token: string): Promise<void> {
      if (token !== correlationId) return
      const remaining = sentencer.flush()
      for (const s of remaining) onSegment(s, correlationId)
    },

    onCancel(_reason: CancelReason, token: string): void {
      if (token !== correlationId) return
      // Sentencer is stateless past flush — nothing to clean up here.
      console.log(`${prefix} cancelled`)
    },

    teardown(): void {},
  }
}
