/**
 * Unicode normalisation for PTI trigger phrases and user messages.
 *
 * MIRROR of backend/modules/knowledge/_pti_normalisation.py — these
 * MUST stay in sync. See INSIGHTS.md.
 *
 * Three steps applied identically to phrases on save and to messages:
 *   1. Unicode NFC composition
 *   2. Locale-aware lowercase (toLocaleLowerCase("en"))
 *   3. Whitespace runs collapsed to single ASCII space, trimmed
 */

const WHITESPACE_RUN = /\s+/gu

export function normalisePhrase(input: string): string {
  let s = input.normalize("NFC")
  // Note: JS has no exact equivalent of Python's str.casefold(). For ASCII
  // and most cases toLocaleLowerCase is sufficient. The backend is the
  // authoritative normaliser — frontend is only used for live UI preview.
  // The single known divergence (German ß) is corrected explicitly below.
  s = s.toLocaleLowerCase("en")
  // Casefold approximation: handle ß explicitly to match Python casefold().
  s = s.replace(/ß/g, "ss")
  s = s.replace(WHITESPACE_RUN, " ").trim()
  return s
}
