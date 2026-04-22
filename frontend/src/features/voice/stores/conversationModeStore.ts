import { create } from 'zustand'
import type { BargeState } from '../bargeController'

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
 *
 * The three reactive-source fields (currentBargeState, sttInFlight,
 * vadActive) are written by useConversationMode and read by usePhase to
 * derive the phase purely. They coexist with the legacy `phase` / `setPhase`
 * pair until Task 4 removes the old pathway.
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
  /** Mirror of bargeController.current?.state; null when no Barge is in flight. */
  currentBargeState: BargeState | null
  /** True while useConversationMode is awaiting the STT promise. */
  sttInFlight: boolean
  /** True between VAD speech-start and speech-end. */
  vadActive: boolean

  enter: () => void
  exit: () => void
  setPhase: (phase: ConversationPhase) => void
  setHolding: (holding: boolean) => void
  setPreviousReasoning: (value: boolean | null) => void
  setCurrentBargeState: (state: BargeState | null) => void
  setSttInFlight: (value: boolean) => void
  setVadActive: (value: boolean) => void
}

export const useConversationModeStore = create<ConversationModeState>((set) => ({
  active: false,
  phase: 'idle',
  isHolding: false,
  previousReasoningOverride: null,
  currentBargeState: null,
  sttInFlight: false,
  vadActive: false,

  enter: () => set({ active: true, phase: 'listening' }),
  exit: () => set({
    active: false,
    phase: 'idle',
    isHolding: false,
    currentBargeState: null,
    sttInFlight: false,
    vadActive: false,
  }),
  setPhase: (phase) => set({ phase }),
  setHolding: (isHolding) => set({ isHolding }),
  setPreviousReasoning: (value) => set({ previousReasoningOverride: value }),
  setCurrentBargeState: (currentBargeState) => set({ currentBargeState }),
  setSttInFlight: (sttInFlight) => set({ sttInFlight }),
  setVadActive: (vadActive) => set({ vadActive }),
}))
