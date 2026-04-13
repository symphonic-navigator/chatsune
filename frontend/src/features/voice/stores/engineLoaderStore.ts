import { create } from 'zustand'
import { modelManager } from '../infrastructure/modelManager'
import { whisperEngine } from '../engines/whisperEngine'
import { kokoroEngine } from '../engines/kokoroEngine'
import { sttRegistry, ttsRegistry } from '../engines/registry'

export type StepStatus = 'waiting' | 'loading' | 'done' | 'error'

export interface StepState {
  id: string
  label: string
  size: string
  status: StepStatus
  error?: string
}

interface EngineLoaderState {
  steps: StepState[]
  loading: boolean
  ready: boolean
  /** Start loading engines in background. Safe to call multiple times. */
  startLoading: () => void
}

const INITIAL_STEPS: StepState[] = [
  { id: 'whisper-tiny', label: 'Speech Recognition', size: '31 MB', status: 'waiting' },
  { id: 'silero-vad', label: 'Voice Detection', size: '1.5 MB', status: 'waiting' },
  { id: 'kokoro-tts', label: 'Speech Synthesis', size: '40 MB', status: 'waiting' },
]

let loadStarted = false

export const useEngineLoader = create<EngineLoaderState>((set, get) => ({
  steps: INITIAL_STEPS.map((s) => ({ ...s })),
  loading: false,
  ready: false,

  startLoading: () => {
    // Only run once
    if (loadStarted || get().ready || get().loading) return
    loadStarted = true

    set({ loading: true })

    const updateStep = (id: string, patch: Partial<StepState>) => {
      set((s) => ({
        steps: s.steps.map((step) => step.id === id ? { ...step, ...patch } : step),
      }))
    }

    async function run() {
      const device = await modelManager.detectDevice()
      console.log(`[Voice Setup] Using device: ${device}`)

      // Step 1: Whisper
      updateStep('whisper-tiny', { status: 'loading' })
      try {
        await whisperEngine.init(device)
        sttRegistry.register(whisperEngine)
        await sttRegistry.setActive(whisperEngine.id)
        updateStep('whisper-tiny', { status: 'done' })
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[Voice Setup] whisper-tiny failed:', err)
        updateStep('whisper-tiny', { status: 'error', error: msg })
        set({ loading: false })
        return
      }

      // Step 2: VAD
      updateStep('silero-vad', { status: 'loading' })
      try {
        await modelManager.markDownloaded('silero-vad')
        updateStep('silero-vad', { status: 'done' })
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[Voice Setup] silero-vad failed:', err)
        updateStep('silero-vad', { status: 'error', error: msg })
        set({ loading: false })
        return
      }

      // Step 3: Kokoro
      updateStep('kokoro-tts', { status: 'loading' })
      try {
        await kokoroEngine.init(device)
        ttsRegistry.register(kokoroEngine)
        await ttsRegistry.setActive(kokoroEngine.id)
        updateStep('kokoro-tts', { status: 'done' })
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[Voice Setup] kokoro-tts failed:', err)
        updateStep('kokoro-tts', { status: 'error', error: msg })
        set({ loading: false })
        return
      }

      console.log('[Voice Setup] All engines ready')
      set({ loading: false, ready: true })
    }

    run()
  },
}))
