import { create } from 'zustand'

/**
 * Lifecycle of the voice companion.
 *
 * - 'active' : normal continuous-voice operation. External STT is the audio sink.
 * - 'paused' : assistant is paused. External STT receives no audio; only the
 *              local Vosk recogniser listens for the resume / status phrases.
 *
 * Transitions are triggered by the voice handler. Side-effecting consumers
 * (audio routing in useConversationMode, vosk feeding) read the current state
 * at their callsite — the store itself is intentionally inert.
 *
 * reset() on continuous-voice stop ensures every fresh session starts in
 * 'active'. No persistence across reloads — the paused state has no meaning
 * outside an active continuous-voice session.
 */
export type VoiceLifecycle = 'active' | 'paused'

interface VoiceLifecycleStore {
  state: VoiceLifecycle
  setPause: () => void
  setActive: () => void
  reset: () => void
}

export const useVoiceLifecycleStore = create<VoiceLifecycleStore>((set) => ({
  state: 'active',
  setPause: () => set({ state: 'paused' }),
  setActive: () => set({ state: 'active' }),
  reset: () => set({ state: 'active' }),
}))
