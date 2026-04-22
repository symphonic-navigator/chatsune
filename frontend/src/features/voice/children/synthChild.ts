import type { GroupChild } from '../../chat/responseTaskGroup'
import type { SpeechSegment, TTSEngine, VoicePreset, NarratorMode } from '../types'
import type { VoiceModulation } from '../pipeline/applyModulation'
import { applyModulation } from '../pipeline/applyModulation'
import { audioPlayback } from '../infrastructure/audioPlayback'

export interface SynthChildOpts {
  correlationId: string
  tts: TTSEngine
  voice: VoicePreset
  narratorVoice: VoicePreset
  mode: NarratorMode
  modulation: VoiceModulation
}

export function createSynthChild(opts: SynthChildOpts): GroupChild & {
  enqueueSegment: (segment: SpeechSegment, token: string) => Promise<void>
} {
  const { correlationId, tts, voice, narratorVoice, modulation } = opts
  // mode is kept in opts for future use (e.g. narrator-mode gating) but is
  // not forwarded to tts.synthesise — the actual TTSEngine.synthesise
  // signature is (text, voice) with no options bag; modulation is applied
  // via applyModulation() on the segment before handing off to audioPlayback.
  const prefix = `[TTS-infer ${correlationId.slice(0, 8)}]`
  let cancelled = false
  let inFlight: Promise<void> = Promise.resolve()

  async function synthesiseOne(segment: SpeechSegment, token: string): Promise<void> {
    if (cancelled || token !== correlationId) return
    const preview = segment.text.slice(0, 40).replace(/\s+/g, ' ')
    console.log(`${prefix} start "${preview}"`)
    const start = performance.now()
    try {
      // Narrator segments use the narrator voice; everything else uses the
      // primary dialogue voice.
      const useVoice = segment.type === 'narration' ? narratorVoice : voice
      const audio = await tts.synthesise(segment.text, useVoice)
      if (cancelled || token !== correlationId) return
      // Apply speed/pitch modulation to the segment before enqueuing so
      // audioPlayback can process it via the SoundTouch worklet.
      audioPlayback.enqueue(audio, applyModulation(segment, modulation), token)
      console.log(`${prefix} done  "${preview}" ${Math.round(performance.now() - start)}ms`)
    } catch (err) {
      console.warn(`${prefix} fail  "${preview}":`, err)
    }
  }

  return {
    name: 'synth',

    enqueueSegment(segment: SpeechSegment, token: string): Promise<void> {
      if (cancelled || token !== correlationId) return Promise.resolve()
      const next = inFlight.then(() => synthesiseOne(segment, token))
      inFlight = next
      return next
    },

    onDelta(): void {},
    async onStreamEnd(): Promise<void> { await inFlight },
    onCancel(_reason, token): void {
      if (token !== correlationId) return
      cancelled = true
    },
    teardown(): void { cancelled = true },
  }
}
