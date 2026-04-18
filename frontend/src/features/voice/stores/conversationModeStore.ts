import { create } from 'zustand'

/**
 * Conversation-mode phase machine.
 *
 *   idle          ← conversation mode is OFF
 *   listening     ← VAD armed, waiting for the user to start speaking
 *   user-speaking ← VAD detected speech start; "Hold to keep talking" is shown
 *   held          ← the user is physically pressing the hold button
 *   transcribing  ← captured audio → STT
 *   thinking      ← LLM is generating tokens (pre-first audio chunk)
 *   speaking      ← TTS audio is playing
 *
 * Transitions are driven by the controller hook (useConversationMode).
 * The store holds only state — not orchestration.
 */
export type ConversationPhase =
  | 'idle'
  | 'listening'
  | 'user-speaking'
  | 'held'
  | 'transcribing'
  | 'thinking'
  | 'speaking'

export interface ConversationModeState {
  active: boolean
  phase: ConversationPhase
  isHolding: boolean
  /** Session reasoning_override captured on entry, so we can restore on exit. */
  previousReasoningOverride: boolean | null

  enter: () => void
  exit: () => void
  setPhase: (phase: ConversationPhase) => void
  setHolding: (holding: boolean) => void
  setPreviousReasoning: (value: boolean | null) => void
}

export const useConversationModeStore = create<ConversationModeState>((set) => ({
  active: false,
  phase: 'idle',
  isHolding: false,
  previousReasoningOverride: null,

  enter: () => set({ active: true, phase: 'listening' }),
  exit: () => set({
    active: false,
    phase: 'idle',
    isHolding: false,
  }),
  setPhase: (phase) => set({ phase }),
  setHolding: (isHolding) => set({ isHolding }),
  setPreviousReasoning: (value) => set({ previousReasoningOverride: value }),
}))
