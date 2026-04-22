import type { GroupChild } from '../../chat/responseTaskGroup'
import { audioPlayback } from '../infrastructure/audioPlayback'

export interface PlaybackChildOpts {
  correlationId: string
  gapMs: number
  onSegmentStart?: () => void
  onFinished?: () => void
}

export function createPlaybackChild(opts: PlaybackChildOpts): GroupChild {
  const { correlationId, gapMs, onSegmentStart, onFinished } = opts
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
      audioPlayback.setCurrentToken(null)
      audioPlayback.clearScope(correlationId)
      drainResolve?.()
      drainResolve = null
    },

    onPause(): void {},
    onResume(): void {},

    teardown(): void {
      audioPlayback.setCurrentToken(null)
    },
  }
}
