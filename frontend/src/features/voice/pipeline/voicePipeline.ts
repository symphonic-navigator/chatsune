import type { CapturedAudio, NarratorMode, PipelineState, VoicePreset } from '../types'
import type { PersonaDto } from '../../../core/types/persona'
import { audioCapture } from '../infrastructure/audioCapture'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { resolveSTTEngine, resolveTTSEngine } from '../engines/resolver'
import { parseForSpeech } from './audioParser'
import { applyModulation, type VoiceModulation } from './applyModulation'
import { useNotificationStore } from '../../../core/store/notificationStore'

export interface VoicePipelineCallbacks {
  onStateChange: (state: PipelineState) => void
  onTranscription: (text: string) => void
}

// Utterances shorter than this are almost certainly accidental PTT taps
// or mic blips.
const MIN_UTTERANCE_MS = 300

class VoicePipelineImpl {
  private callbacks: VoicePipelineCallbacks | null = null
  private mode: 'push-to-talk' | 'continuous' = 'push-to-talk'
  private state: PipelineState = { phase: 'idle' }

  // Generation counter: incremented on every new recording session.
  // handleAudio checks this to discard results from stale sessions.
  private generation = 0

  setCallbacks(callbacks: VoicePipelineCallbacks): void { this.callbacks = callbacks }

  private setState(state: PipelineState): void {
    this.state = state
    this.callbacks?.onStateChange(state)
  }

  async startRecording(mode: 'push-to-talk' | 'continuous'): Promise<void> {
    // If a previous session is still transcribing, cancel it
    if (this.state.phase === 'transcribing' || this.state.phase === 'recording') {
      this.generation++ // invalidate in-flight transcription
      try { audioCapture.stopPTT() } catch { /* may not be active */ }
    }

    this.mode = mode
    this.generation++
    this.stopPlayback()

    const gen = this.generation
    const captureCallbacks = {
      onSpeechStart: () => { this.setState({ phase: 'recording' }) },
      onSpeechEnd: async (audio: CapturedAudio) => {
        if (gen !== this.generation) return // stale session, discard
        this.setState({ phase: 'transcribing' })
        await this.handleAudio(audio, gen)
      },
      onVolumeChange: () => {},
    }

    if (mode === 'push-to-talk') {
      this.setState({ phase: 'recording' })
      await audioCapture.startPTT(captureCallbacks)
    } else {
      this.setState({ phase: 'listening' })
      await audioCapture.startContinuous(captureCallbacks)
    }
  }

  stopRecording(): void {
    if (this.mode === 'push-to-talk') {
      if (this.state.phase === 'recording') {
        // Show transcribing spinner immediately so user sees feedback
        this.setState({ phase: 'transcribing' })
      }
      audioCapture.stopPTT()
    } else {
      audioCapture.stopContinuous()
      if (this.state.phase === 'recording' || this.state.phase === 'listening') {
        this.setState({ phase: 'idle' })
      }
    }
  }

  private async handleAudio(audio: CapturedAudio, gen: number): Promise<void> {
    // Skip empty audio (stopPTT called before any samples were collected)
    // or utterances too short to contain real speech. Accidental PTT taps
    // or mic blips would otherwise burn an API call and return HTTP 400
    // from xAI for "no speech detected". Continuous mode isn't affected
    // because the VAD gates segment starts itself.
    if (
      (audio.pcm.length === 0 && audio.blob.size === 0) ||
      audio.durationMs < MIN_UTTERANCE_MS
    ) {
      if (gen === this.generation) this.setState({ phase: 'idle' })
      return
    }
    const stt = resolveSTTEngine()
    if (!stt) { this.setState({ phase: 'idle' }); return }
    try {
      const result = await stt.transcribe(audio)
      if (gen !== this.generation) return // new session started while transcribing
      const text = result.text.trim()
      if (text) {
        this.callbacks?.onTranscription(text)
      }
    } catch (err) {
      console.error('[VoicePipeline] Transcription failed:', err)
      const isAuthError = err instanceof Error && (err.message.includes('401') || err.message.includes('Unauthorized'))
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Transcription failed',
        message: isAuthError
          ? 'Couldn\'t transcribe audio — check your Mistral API key.'
          : 'Couldn\'t transcribe audio — check the console for details.',
      })
    } finally {
      if (gen !== this.generation) return // don't touch state if a new session took over
      if (this.mode === 'continuous') this.setState({ phase: 'listening' })
      else this.setState({ phase: 'idle' })
    }
  }

  async speakResponse(
    text: string,
    dialogueVoice: VoicePreset,
    narratorVoice: VoicePreset,
    mode: NarratorMode,
    modulation: VoiceModulation,
    persona?: PersonaDto | null,
    supportsExpressive: boolean = false,
  ): Promise<void> {
    const tts = resolveTTSEngine(persona ?? ({} as PersonaDto))
    if (!tts) return
    const segments = parseForSpeech(text, mode, supportsExpressive)
    if (segments.length === 0) return
    this.setState({ phase: 'speaking', segment: 0, total: segments.length })
    audioPlayback.setCallbacks({
      onSegmentStart: (seg) => {
        const idx = segments.findIndex((s) => s.text === seg.text && s.type === seg.type)
        this.setState({ phase: 'speaking', segment: idx, total: segments.length })
      },
      onFinished: () => {
        if (this.mode === 'continuous') this.setState({ phase: 'listening' })
        else this.setState({ phase: 'idle' })
      },
    })
    for (const segment of segments) {
      const voice = segment.type === 'voice' ? dialogueVoice : narratorVoice
      const audio = await tts.synthesise(segment.text, voice)
      audioPlayback.enqueue(audio, applyModulation(segment, modulation))
    }
  }

  stopPlayback(): void { audioPlayback.stopAll() }
  skipSegment(): void { audioPlayback.skipCurrent() }
  getPhase(): PipelineState['phase'] { return this.state.phase }

  dispose(): void {
    this.generation++ // invalidate any in-flight transcriptions
    this.stopRecording()
    this.stopPlayback()
    audioPlayback.dispose()
    this.callbacks = null
    this.setState({ phase: 'idle' })
  }
}

export const voicePipeline = new VoicePipelineImpl()
