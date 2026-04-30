import type { GroupChild } from './responseTaskGroup'
import { createChatStoreSink } from './children/chatStoreSink'
import { createSentencerChild } from '../voice/children/sentencerChild'
import { createPauserChild } from '../voice/children/pauserChild'
import { createSynthChild } from '../voice/children/synthChild'
import { createPlaybackChild } from '../voice/children/playbackChild'
import { createStreamingSentencer } from '../voice/pipeline/streamingSentencer'
import { useChatStore } from '../../core/store/chatStore'
import type { NarratorMode, TTSEngine, VoicePreset } from '../voice/types'
import type { VoiceModulation } from '../voice/pipeline/applyModulation'
import type { PendingEffect } from '../integrations/responseTagProcessor'

export type Mode = 'text' | 'voice'

export interface VoiceBuildOpts {
  tts: TTSEngine
  voice: VoicePreset
  narratorVoice: VoicePreset
  narratorMode: NarratorMode
  modulation: VoiceModulation
  gapMs: number
  narratorEnabled: boolean
  supportsExpressiveMarkup?: boolean
}

export interface BuildChildrenOpts {
  correlationId: string
  sessionId: string
  mode: Mode
  voice?: VoiceBuildOpts
  /** Per-stream parking lot for inline-trigger effects awaiting a sentence
   *  boundary. Threaded into the sentencer's parser so sentence-bound
   *  triggers can be claimed and stamped onto the matching SpeechSegment. */
  pendingEffectsMap?: Map<string, PendingEffect>
  /** Origin of the synth chunks emitted by this Group. Stamped onto every
   *  inline-trigger event surfaced from this pipeline. Defaults to
   *  `'live_stream'` for the active voice-mode chat reply. */
  streamSource?: 'live_stream' | 'read_aloud'
}

/**
 * Build the list of GroupChildren for a new response. Text-mode returns
 * only chatStoreSink; voice-mode adds the sentencer/pauser/synth/playback
 * chain with voice-internal DI wiring (sentencer.onSegment → pauser →
 * synth.enqueueSegment).
 */
export function buildChildren(opts: BuildChildrenOpts): GroupChild[] {
  const { correlationId, sessionId, mode, voice } = opts
  const streamSource = opts.streamSource ?? 'live_stream'

  const children: GroupChild[] = [
    createChatStoreSink({
      sessionId,
      correlationId,
      chatStore: useChatStore.getState() as {
        startStreaming(correlationId: string): void
        appendStreamingContent(delta: string): void
        cancelStreaming(): void
      },
    }),
  ]

  if (mode === 'voice' && voice) {
    const sentencer = createStreamingSentencer(
      voice.narratorMode,
      voice.supportsExpressiveMarkup ?? false,
      opts.pendingEffectsMap ?? null,
      streamSource,
    )

    const synth = createSynthChild({
      correlationId,
      tts: voice.tts,
      voice: voice.voice,
      narratorVoice: voice.narratorVoice,
      mode: voice.narratorMode,
      modulation: voice.modulation,
      streamSource,
    })

    const pauser = createPauserChild({
      correlationId,
      onSegmentReleased: (seg, token) => { void synth.enqueueSegment(seg, token) },
    })

    const sentencerChild = createSentencerChild({
      correlationId,
      sentencer,
      onSegment: (seg, token) => pauser.pushSegment(seg, token),
    })

    const playback = createPlaybackChild({
      correlationId,
      gapMs: voice.gapMs,
    })

    children.push(sentencerChild, pauser, synth, playback)
  }

  return children
}
