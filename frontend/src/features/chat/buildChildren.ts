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
}

/**
 * Build the list of GroupChildren for a new response. Text-mode returns
 * only chatStoreSink; voice-mode adds the sentencer/pauser/synth/playback
 * chain with voice-internal DI wiring (sentencer.onSegment → pauser →
 * synth.enqueueSegment).
 */
export function buildChildren(opts: BuildChildrenOpts): GroupChild[] {
  const { correlationId, sessionId, mode, voice } = opts

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
    )

    const synth = createSynthChild({
      correlationId,
      tts: voice.tts,
      voice: voice.voice,
      narratorVoice: voice.narratorVoice,
      mode: voice.narratorMode,
      modulation: voice.modulation,
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
