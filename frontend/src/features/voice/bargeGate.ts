import type { ResponseTaskGroup } from '../chat/responseTaskGroup'

export interface ShouldSuppressBargeInput {
  /** Live value of useBargeSettingsStore.enabled. */
  enabled: boolean
  /** Active Group's state, or null when no Group is active. */
  groupState: ResponseTaskGroup['state'] | null
}

/**
 * Pure decision function: given the user's barging preference and the
 * active Group's lifecycle state, should an incoming VAD onset be
 * suppressed (i.e. NOT promoted into a Barge)?
 *
 * Rule: suppress iff the user has turned barging off AND the persona
 * is currently emitting audio (Group is `streaming` or `tailing`,
 * matching the `speaking` phase from derivePhase).
 *
 * `before-first-delta` (phase `thinking`) is intentionally NOT
 * suppressed — there's no audio yet, the mic is naturally closed by
 * the STT pipeline anyway, and showing a suppression cue here would
 * be misleading.
 *
 * Listening / idle (groupState === null) is never suppressed:
 * barging-off only changes behaviour while the persona is speaking;
 * fresh user speech in a quiet moment must always go through.
 */
export function shouldSuppressBarge(input: ShouldSuppressBargeInput): boolean {
  if (input.enabled) return false
  return input.groupState === 'streaming' || input.groupState === 'tailing'
}
