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
 * The phase itself is no longer stored. It is derived by `usePhase()` from:
 *   - the `active` / `isHolding` flags on this store
 *   - the three reactive-source fields below (currentBargeState,
 *     sttInFlight, vadActive), written by `useConversationMode`
 *   - the active Group's state, read via `subscribeActiveGroup`
 *
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
  isHolding: boolean
  /** Whether the microphone is muted while in live mode. */
  micMuted: boolean
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
  setHolding: (holding: boolean) => void
  /** Mute or unmute the microphone while in live mode. */
  setMicMuted: (muted: boolean) => void
  setPreviousReasoning: (value: boolean | null) => void
  setCurrentBargeState: (state: BargeState | null) => void
  setSttInFlight: (value: boolean) => void
  setVadActive: (value: boolean) => void
}

export const useConversationModeStore = create<ConversationModeState>((set) => ({
  active: false,
  isHolding: false,
  micMuted: false,
  previousReasoningOverride: null,
  currentBargeState: null,
  sttInFlight: false,
  vadActive: false,

  enter: () => set({ active: true }),
  exit: () => set({
    active: false,
    isHolding: false,
    micMuted: false,
    currentBargeState: null,
    sttInFlight: false,
    vadActive: false,
  }),
  setHolding: (isHolding) => set({ isHolding }),
  setMicMuted: (micMuted) => set({ micMuted }),
  setPreviousReasoning: (value) => set({ previousReasoningOverride: value }),
  setCurrentBargeState: (currentBargeState) => set({ currentBargeState }),
  setSttInFlight: (sttInFlight) => set({ sttInFlight }),
  setVadActive: (vadActive) => set({ vadActive }),
}))
