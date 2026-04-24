import { create } from 'zustand'
import type { PipelineState } from '../types'
import { voicePipeline } from '../pipeline/voicePipeline'

interface VoicePipelineState {
  state: PipelineState
  setState: (state: PipelineState) => void
  /** Cancel any in-progress TTS playback, resetting the pipeline to idle. */
  stopPlayback: () => void
}

export const useVoicePipeline = create<VoicePipelineState>((set) => ({
  state: { phase: 'idle' },
  setState: (state) => set({ state }),
  stopPlayback: () => {
    voicePipeline.stopPlayback()
    set({ state: { phase: 'idle' } })
  },
}))
