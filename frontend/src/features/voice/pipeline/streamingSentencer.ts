import type { NarratorMode, SpeechSegment } from '../types'
import { parseForSpeech } from './audioParser'
import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'
import { effectiveLength } from './effectiveLength'

export interface StreamingSentencer {
  push(delta: string): SpeechSegment[]
  flush(): SpeechSegment[]
  reset(): void
}

const SENTENCE_END = /[.!?\n]/

// Per-sentence length thresholds. The first sentence in the stream must
// carry at least 20 effective characters to be worth emitting on its own;
// every follow-up must clear 30. Effective length ignores expression tags
// (inline and wrapping) because they carry no spoken content.
const FIRST_SENTENCE_MIN = 20
const FOLLOWUP_SENTENCE_MIN = 30

// Scan `text` up to `limit` and return the index of the last position that is
// simultaneously (a) a sentence boundary the downstream splitter will honour
// and (b) not inside any unterminated markdown / OOC / quote construct. Returns
// -1 if no such position exists in the window. The invariant that matters: we
// must never hand a chunk to `parseForSpeech` that would strip an unterminated
// fence (```…) or OOC marker ((…)) and thereby mangle the text on the next
// push — so we require each tracked construct to be balanced at the cut point.
//
// In addition, two content guards are applied:
//   Guard 1 — length: the chunk [start, cutPoint) must have at least
//     `minEffectiveLength` effective characters (tags excluded).
//   Guard 2 — no-space: for non-newline cuts, the chunk must contain at
//     least one whitespace character, so that abbreviations like "z.B."
//     never count as a complete sentence.
function findSafeCutPoint(
  text: string,
  start: number,
  mode: NarratorMode,
  minEffectiveLength: number,
): number {
  let fenceOpen = false
  let inlineTickOpen = false
  let oocDepth = 0
  let doubleQuoteOpen = false
  let smartQuoteOpen = false
  let singleQuoteOpen = false
  let asteriskOpen = false
  let lineStart = 0

  let lastSafeEnd = -1

  const trackQuotes = mode === 'play' || mode === 'narrate'
  const trackAsterisk = mode === 'play'

  for (let i = 0; i < text.length; i++) {
    // Fenced code block: ``` toggles; everything inside is opaque to the
    // other scanners, so we `continue` after toggling.
    if (text[i] === '`' && text[i + 1] === '`' && text[i + 2] === '`') {
      fenceOpen = !fenceOpen
      i += 2
      continue
    }
    if (fenceOpen) continue

    const ch = text[i]

    if (ch === '\n') {
      // Newlines close inline-tick and single-quote state: those constructs
      // are line-scoped in practice.
      inlineTickOpen = false
      singleQuoteOpen = false
      lineStart = i + 1
    }

    if (ch === '`') {
      inlineTickOpen = !inlineTickOpen
      continue
    }
    if (inlineTickOpen) continue

    if (ch === '(' && text[i + 1] === '(') {
      oocDepth++
      i += 1
      continue
    }
    if (ch === ')' && text[i + 1] === ')' && oocDepth > 0) {
      oocDepth--
      i += 1
      continue
    }
    if (oocDepth > 0) continue

    if (trackQuotes) {
      if (ch === '"') {
        doubleQuoteOpen = !doubleQuoteOpen
      } else if (ch === '“') {
        smartQuoteOpen = true
      } else if (ch === '”') {
        smartQuoteOpen = false
      } else if (ch === "'" && !singleQuoteOpen && isWordBoundaryLeft(text, i)) {
        // Only open a single-quote pair at a word boundary, so that
        // apostrophes inside words ("it's", "don't") don't flip the state.
        singleQuoteOpen = true
      } else if (ch === "'" && singleQuoteOpen) {
        singleQuoteOpen = false
      }
    }

    if (trackAsterisk && ch === '*') {
      asteriskOpen = !asteriskOpen
    }

    if (i >= start && SENTENCE_END.test(ch)) {
      if (ch === '.' && text[i - 1] === '.') continue
      const allBalanced =
        !fenceOpen &&
        !inlineTickOpen &&
        oocDepth === 0 &&
        (!trackQuotes || (!doubleQuoteOpen && !smartQuoteOpen && !singleQuoteOpen)) &&
        (!trackAsterisk || !asteriskOpen)
      if (!allBalanced) continue

      if (ch === '\n') {
        // Hard line break — sentenceSplitter treats newlines as boundaries.
        // Guard 1 applies (length), Guard 2 does not (newlines are always
        // genuine boundaries even inside an abbreviation-only prefix).
        const candidate = i + 1
        if (effectiveLength(text.slice(start, candidate)) >= minEffectiveLength) {
          lastSafeEnd = candidate
        }
        continue
      }

      // Sentence-ending punctuation. Safe to cut when followed by:
      //   (a) whitespace + (newline | uppercase | emoji/pictograph)
      //   (b) an emoji/pictograph directly (no whitespace) — LLM decoration
      //       like "Great!😀" should end the sentence at the punctuation.
      // Refuse to cut inside decimals ("3.14") or dotted abbreviations
      // ("Dr.Smith"): a letter or digit immediately after the punctuation
      // suppresses the cut.
      const nextIdx = i + 1
      if (nextIdx >= text.length) {
        // Mid-stream: refuse to cut exactly at EOF — more text may arrive
        // that extends the sentence.
        continue
      }
      const next = text[nextIdx]
      const nextIsWhitespace = next === ' ' || next === '\t' || next === '\n'
      if (!nextIsWhitespace) {
        // Case (b): only accept pictographic chars directly after punctuation.
        if (isPictographAt(text, nextIdx)) {
          tryRegisterCut(text, start, nextIdx, minEffectiveLength, (end) => {
            lastSafeEnd = end
          })
          continue
        }
        // Case (c): one or more closing tags directly after punctuation —
        // look through them to find the whitespace + sentence-start that
        // follows. This allows cuts in expressive-markup text like
        // "hello.</whisper> Next" where the tag is transparent punctuation.
        let k = nextIdx
        while (k < text.length && text[k] === '<' && text[k + 1] === '/') {
          const closeEnd = text.indexOf('>', k)
          if (closeEnd === -1) break
          k = closeEnd + 1
        }
        if (k > nextIdx) {
          // We consumed at least one closing tag. Now apply the normal
          // whitespace + sentence-start check at position k.
          const afterTags = k
          while (k < text.length && (text[k] === ' ' || text[k] === '\t')) k++
          if (k < text.length) {
            const afterTagChar = text[k]
            if (
              afterTagChar === '\n' ||
              isUppercaseSentenceStart(afterTagChar) ||
              isPictographAt(text, k)
            ) {
              // Cut includes the closing tags so the emitted chunk is balanced.
              tryRegisterCut(text, start, afterTags, minEffectiveLength, (end) => {
                lastSafeEnd = end
              })
            }
          }
        }
        continue
      }

      // Walk past the whitespace run.
      let j = nextIdx
      while (j < text.length && (text[j] === ' ' || text[j] === '\t')) j++
      if (j >= text.length) {
        // Trailing whitespace only — wait for more text.
        continue
      }
      const after = text[j]
      if (after === '\n' || isUppercaseSentenceStart(after) || isPictographAt(text, j)) {
        tryRegisterCut(text, start, nextIdx, minEffectiveLength, (end) => {
          lastSafeEnd = end
        })
      }
    }
  }

  void lineStart
  return lastSafeEnd
}

// Apply Guard 1 (effective-length threshold) and Guard 2 (at least one
// whitespace in the candidate chunk) before accepting a cut. Both guards
// apply to punctuation-based cuts; newline cuts bypass Guard 2 (see the
// `ch === '\n'` branch) but still use this helper for Guard 1 indirectly.
function tryRegisterCut(
  text: string,
  start: number,
  candidate: number,
  minEffectiveLength: number,
  register: (end: number) => void,
): void {
  const chunk = text.slice(start, candidate)
  if (effectiveLength(chunk) < minEffectiveLength) return
  if (!/\s/.test(chunk)) return
  register(candidate)
}

function isWordBoundaryLeft(text: string, i: number): boolean {
  if (i === 0) return true
  const prev = text[i - 1]
  return !/[A-Za-z0-9À-ɏ]/.test(prev)
}

function isUppercaseSentenceStart(ch: string): boolean {
  return /[A-ZÄÖÜ]/.test(ch)
}

// Whether the code point at `i` is an emoji / pictograph. Handles surrogate
// pairs (most emojis live in the supplementary plane). Used to decide whether
// a char following sentence-end punctuation is decoration (like 😀) rather
// than a word-continuation such as "3.14" or "Dr.Smith".
function isPictographAt(text: string, i: number): boolean {
  const cp = text.codePointAt(i)
  if (cp === undefined) return false
  return /\p{Extended_Pictographic}/u.test(String.fromCodePoint(cp))
}

class StreamingSentencerImpl implements StreamingSentencer {
  private buffer = ''
  private committedIndex = 0
  private readonly mode: NarratorMode
  private readonly supportsExpressiveMarkup: boolean
  private wrapStack: string[] = []
  // True once at least one speakable SpeechSegment has been emitted. Gates
  // the length-threshold choice (20 chars for the very first sentence,
  // 30 for every subsequent one). A chunk that parseForSpeech reduces to
  // nothing (e.g. tags only) does not flip this flag — the stream stays in
  // "first sentence" mode until real speech has left the sentencer.
  private hasEmitted = false

  constructor(mode: NarratorMode, supportsExpressiveMarkup: boolean) {
    this.mode = mode
    this.supportsExpressiveMarkup = supportsExpressiveMarkup
  }

  push(delta: string): SpeechSegment[] {
    if (!delta) return []
    this.buffer += delta
    const threshold = this.hasEmitted ? FOLLOWUP_SENTENCE_MIN : FIRST_SENTENCE_MIN
    const safeEnd = findSafeCutPoint(this.buffer, this.committedIndex, this.mode, threshold)
    if (safeEnd <= this.committedIndex) return []
    const chunk = this.buffer.slice(this.committedIndex, safeEnd)
    this.committedIndex = safeEnd
    const segments = this.emitChunk(chunk)
    if (segments.length > 0) this.hasEmitted = true
    return segments
  }

  flush(): SpeechSegment[] {
    // Guard 3: flush bypasses length and whitespace guards. Whatever is left
    // in the buffer goes out — otherwise a legitimate short closing sentence
    // like "Ja." would never become audible.
    if (this.committedIndex >= this.buffer.length) return []
    const rest = this.buffer.slice(this.committedIndex)
    this.committedIndex = this.buffer.length
    const segments = this.emitChunk(rest)
    if (segments.length > 0) this.hasEmitted = true
    return segments
  }

  reset(): void {
    this.buffer = ''
    this.committedIndex = 0
    this.wrapStack = []
    this.hasEmitted = false
  }

  private emitChunk(chunk: string): SpeechSegment[] {
    if (!this.supportsExpressiveMarkup) {
      return parseForSpeech(chunk, this.mode, this.supportsExpressiveMarkup)
    }
    const entering = [...this.wrapStack]
    const leaving = scanSegment(chunk, entering)
    const wrapped = wrapSegmentWithActiveStack(chunk, entering, leaving)
    this.wrapStack = leaving
    return parseForSpeech(wrapped, this.mode, this.supportsExpressiveMarkup)
  }
}

export function createStreamingSentencer(
  mode: NarratorMode,
  supportsExpressiveMarkup: boolean = false,
): StreamingSentencer {
  return new StreamingSentencerImpl(mode, supportsExpressiveMarkup)
}
