import { create } from 'zustand'

/**
 * Lifecycle state of the voice companion.
 *
 * - 'on'  : normal continuous-voice operation. External STT is the audio sink.
 * - 'off' : assistant is paused. External STT receives no audio; only the
 *           local Vosk recogniser listens for the wake phrase.
 *
 * Transitions are triggered by the companion handler. Side-effecting
 * consumers (audio routing in useConversationMode, vosk feeding) read the
 * current state at their callsite — the store itself is intentionally inert.
 *
 * Reset on continuous-voice stop ensures every fresh session starts in ON.
 * No persistence across reloads — the OFF state has no meaning outside an
 * active continuous-voice session.
 */
export type CompanionLifecycle = 'on' | 'off'

interface CompanionLifecycleStore {
  state: CompanionLifecycle
  setOff: () => void
  setOn: () => void
  reset: () => void
}

export const useCompanionLifecycleStore = create<CompanionLifecycleStore>((set) => ({
  state: 'on',
  setOff: () => set({ state: 'off' }),
  setOn: () => set({ state: 'on' }),
  reset: () => set({ state: 'on' }),
}))
