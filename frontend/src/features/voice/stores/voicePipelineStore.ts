import { create } from 'zustand'
import type { PipelineState } from '../types'

interface VoicePipelineState { state: PipelineState; setState: (state: PipelineState) => void }

export const useVoicePipeline = create<VoicePipelineState>((set) => ({
  state: { phase: 'idle' },
  setState: (state) => set({ state }),
}))
