/**
 * derivePhase — pure reducer from reactive sources to the conversation phase.
 *
 * See devdocs/voice-barge-structural-redesign.md §4 (Phase: derived, not
 * written). No React, no side effects, no imports beyond types.
 *
 * Rule priority (first match wins):
 *   1. !active                       → 'idle'
 *   2. isHolding                     → 'held'
 *   3. bargeState === 'pending-stt'  → 'transcribing' if sttInFlight else 'user-speaking'
 *   4. vadActive                     → 'user-speaking'
 *   5. fall through by groupState:
 *        'before-first-delta'        → 'thinking'
 *        'streaming' | 'tailing'     → 'speaking'
 *        anything else               → 'listening'
 *
 * Barge states 'confirmed' / 'resumed' / 'stale' / 'abandoned' are never
 * observed by the hook in practice — the controller nulls its `current`
 * reference immediately after each. They still fall through to the
 * groupState rule here to keep the function total and deterministic.
 */

import type { ResponseTaskGroup } from '../chat/responseTaskGroup'
import type { BargeState } from './bargeController'
import type { ConversationPhase } from './stores/conversationModeStore'

export interface DerivePhaseInput {
  /** Whether conversation mode is on. */
  active: boolean
  /** Whether the user is physically pressing the hold button. */
  isHolding: boolean
  /** True between VAD speech-start and speech-end. */
  vadActive: boolean
  /** Current in-flight Barge state, or null when no Barge is in flight. */
  bargeState: BargeState | null
  /** True while useConversationMode is awaiting the STT promise. */
  sttInFlight: boolean
  /** Active Group's state, or null when no Group is active. */
  groupState: ResponseTaskGroup['state'] | null
}

export function derivePhase(input: DerivePhaseInput): ConversationPhase {
  if (!input.active) return 'idle'
  if (input.isHolding) return 'held'
  if (input.bargeState === 'pending-stt') {
    return input.sttInFlight ? 'transcribing' : 'user-speaking'
  }
  if (input.vadActive) return 'user-speaking'
  switch (input.groupState) {
    case 'before-first-delta':
      return 'thinking'
    case 'streaming':
    case 'tailing':
      return 'speaking'
    default:
      return 'listening'
  }
}
