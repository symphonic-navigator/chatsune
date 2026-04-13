import type { PipelineState, VoicePreset } from '../types'
import { audioCapture } from '../infrastructure/audioCapture'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { sttRegistry, ttsRegistry } from '../engines/registry'
import { parseForSpeech } from './audioParser'

export interface VoicePipelineCallbacks {
  onStateChange: (state: PipelineState) => void
  onTranscription: (text: string) => void
}

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
    this.mode = mode
    this.generation++
    this.stopPlayback()

    const gen = this.generation
    const captureCallbacks = {
      onSpeechStart: () => { this.setState({ phase: 'recording' }) },
      onSpeechEnd: async (audio: Float32Array) => {
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
      audioCapture.stopPTT()
    } else {
      audioCapture.stopContinuous()
      if (this.state.phase === 'recording' || this.state.phase === 'listening') {
        this.setState({ phase: 'idle' })
      }
    }
  }

  private async handleAudio(audio: Float32Array, gen: number): Promise<void> {
    // Skip empty audio (e.g. stopPTT called before any samples were collected)
    if (audio.length === 0) {
      if (gen === this.generation) this.setState({ phase: 'idle' })
      return
    }
    const stt = sttRegistry.active()
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
    } finally {
      if (gen !== this.generation) return // don't touch state if a new session took over
      if (this.mode === 'continuous') this.setState({ phase: 'listening' })
      else this.setState({ phase: 'idle' })
    }
  }

  async speakResponse(
    text: string, dialogueVoice: VoicePreset, narratorVoice: VoicePreset, roleplayMode: boolean,
  ): Promise<void> {
    const tts = ttsRegistry.active()
    if (!tts) return
    const segments = parseForSpeech(text, roleplayMode)
    if (segments.length === 0) return
    this.setState({ phase: 'speaking', segment: 0, total: segments.length })
    audioPlayback.setCallbacks({
      onSegmentStart: (seg) => {
        const idx = segments.findIndex((s) => s === seg)
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
      audioPlayback.enqueue(audio, segment)
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
