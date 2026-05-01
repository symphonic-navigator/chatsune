/**
 * Vosk constrained grammar for the paused-state recogniser.
 *
 * Discipline (lifted from VOSK-STT.md spike):
 *  - Only the accept phrases are actionable. Any other final-result text is
 *    rejected at recogniser level via ACCEPT_TEXTS.
 *  - Every standalone phonetic distractor of 'voice' appears both standalone
 *    AND with each subcommand — without the second-word forms, the second
 *    word collapses onto the accept set when the first word is misheard
 *    (VOSK-STT.md pitfall #7).
 *  - 'voice' itself appears as a standalone distractor: a user who says
 *    'voice' and trails off must drop, not collapse onto an accept entry.
 *  - '[unk]' is mandatory: gives Viterbi a "this isn't a wake phrase" path
 *    and prevents near-misses from collapsing onto the accept set with
 *    full confidence (VOSK-STT.md pitfall #6).
 *  - 'voice off' / 'voice pause' / 'voice of' are deliberately omitted: in
 *    the paused state, hearing them again is a no-op, and adding the path
 *    only increases competition for the decoder.
 *
 * If false positives surface in production from new word neighbours,
 * extend BOTH the standalone list AND the second-word phrases. Skipping
 * the second-word entries reproduces pitfall #7.
 */

export const VOSK_GRAMMAR: readonly string[] = [
  // Accept set
  'voice on',
  'voice continue',
  'voice resume',
  'voice status',
  'voice state',

  // Phonetic distractors of 'voice' — standalone (VOSK-STT.md pitfall #6)
  'noise',
  'choice',
  'boys',
  'voice',
  'poise',
  'vice',
  'rice',

  // Phonetic distractors of 'voice' — with each subcommand (pitfall #7)
  'noise on',  'noise continue',  'noise resume',  'noise status',  'noise state',
  'choice on', 'choice continue', 'choice resume', 'choice status', 'choice state',
  'boys on',   'boys continue',   'boys resume',   'boys status',   'boys state',
  'poise on',  'poise continue',  'poise resume',  'poise status',  'poise state',
  'vice on',   'vice continue',   'vice resume',   'vice status',   'vice state',
  'rice on',   'rice continue',   'rice resume',   'rice status',   'rice state',

  // Garbage model
  '[unk]',
]

/** Set of texts that are valid resume / status phrases. Recogniser drops anything else. */
export const ACCEPT_TEXTS: ReadonlySet<string> = new Set([
  'voice on',
  'voice continue',
  'voice resume',
  'voice status',
  'voice state',
])
