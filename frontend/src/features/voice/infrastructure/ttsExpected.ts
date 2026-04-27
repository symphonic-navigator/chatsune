/**
 * Pure predicate: should the VoiceVisualiser show *something* right now,
 * even if no audio is currently playing? Used to drive the noisy-flatline
 * "TTS expected" state.
 *
 * Three or-branches:
 *   (a) Audio is actually playing — strongest signal, never a false negative.
 *   (b) The read-aloud pipeline is synthesising or playing — covers manual
 *       and auto-read once read-aloud has taken over.
 *   (c) An LLM response group is in flight, AND either continuous voice
 *       (live mode) is on, or auto-read is enabled for that group's
 *       session. Covers the early window before audio first arrives.
 */
export interface TtsExpectedInput {
  /**
   * True iff `audioPlayback.isActive()`. That getter returns true also while
   * playback is *paused* (tap-to-pause), so this branch keeps the predicate
   * true through pauses without dropping back to the noise flatline for a
   * frame on resume. If `audioPlayback.isActive()` is ever tightened to
   * exclude the paused state, revisit this contract.
   */
  audioActive: boolean
  /** True iff a read-aloud session is synthesising or playing. */
  isReadingAloud: boolean
  /** True iff `getActiveGroup() !== null`. */
  hasActiveGroup: boolean
  /** True iff conversation mode is currently active (continuous voice). */
  liveModeActive: boolean
  /** True iff the active group's session has auto-read on in the cockpit. */
  autoReadEnabledForActiveGroup: boolean
}

export function computeTtsExpected(input: TtsExpectedInput): boolean {
  if (input.audioActive) return true
  if (input.isReadingAloud) return true
  if (input.hasActiveGroup) {
    if (input.liveModeActive) return true
    if (input.autoReadEnabledForActiveGroup) return true
  }
  return false
}
