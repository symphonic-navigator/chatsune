/**
 * Vosk constrained grammar for the OFF-state wake-phrase detector.
 *
 * Vocabulary discipline (lifted from VOSK-STT.md spike):
 *  - Only the accept phrases ("companion on", "companion status") are
 *    actionable. Any other final-result text is rejected at recogniser
 *    level via ACCEPT_TEXTS.
 *  - Phonetic distractors must appear both standalone AND as <word> on /
 *    <word> status — without the second-word forms, the second word
 *    collapses onto the accept set when the first word is misheard
 *    (VOSK-STT.md pitfall #7).
 *  - "[unk]" is mandatory: gives Viterbi a "this isn't a wake phrase" path
 *    and prevents near-misses from collapsing onto the accept set with
 *    full confidence (VOSK-STT.md pitfall #6).
 *  - "companion off" is deliberately omitted: in the OFF state, hearing
 *    it again would be a no-op, and adding the path only increases
 *    competition for the decoder.
 *
 * If false positives appear in production from new word neighbours,
 * extend BOTH the standalone list AND the second-word phrases. Skipping
 * the second-word entries reproduces pitfall #7.
 */

export const VOSK_GRAMMAR: readonly string[] = [
  // Accept set
  'companion on',
  'companion status',

  // Phonetic distractors — standalone (VOSK-STT.md pitfall #6)
  'campaign',
  'champion',
  'company',
  'compass',
  'common',
  'complete',
  'complain',

  // Phonetic distractors — with second word (VOSK-STT.md pitfall #7)
  'campaign on',
  'champion on',
  'company on',
  'compass on',
  'common on',
  'complete on',
  'complain on',
  'campaign status',
  'champion status',
  'company status',
  'compass status',
  'common status',
  'complete status',
  'complain status',

  // Garbage model
  '[unk]',
]

/** Set of texts that are valid wake/status phrases. Recogniser drops anything else. */
export const ACCEPT_TEXTS: ReadonlySet<string> = new Set([
  'companion on',
  'companion status',
])
