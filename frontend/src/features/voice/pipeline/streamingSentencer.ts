import type { NarratorMode, SpeechSegment } from '../types'
import { parseForSpeech } from './audioParser'
import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'

export interface StreamingSentencer {
  push(delta: string): SpeechSegment[]
  flush(): SpeechSegment[]
  reset(): void
}

const SENTENCE_END = /[.!?\n]/

// Scan `text` up to `limit` and return the index of the last position that is
// simultaneously (a) a sentence boundary the downstream splitter will honour
// and (b) not inside any unterminated markdown / OOC / quote construct. Returns
// -1 if no such position exists in the window. The invariant that matters: we
// must never hand a chunk to `parseForSpeech` that would strip an unterminated
// fence (```…) or OOC marker ((…)) and thereby mangle the text on the next
// push — so we require each tracked construct to be balanced at the cut point.
function findSafeCutPoint(text: string, start: number, mode: NarratorMode): number {
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
      } else if (ch === '\u201c') {
        smartQuoteOpen = true
      } else if (ch === '\u201d') {
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
        lastSafeEnd = i + 1
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
          lastSafeEnd = nextIdx
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
              isPictographAt(text, k) ||
              isLetter(afterTagChar)
            ) {
              // Cut includes the closing tags so the emitted chunk is balanced.
              lastSafeEnd = afterTags
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
      if (after === '\n' || isUppercaseSentenceStart(after) || isPictographAt(text, j) || isLetter(after)) {
        lastSafeEnd = nextIdx
      }
    }
  }

  void lineStart
  return lastSafeEnd
}

function isWordBoundaryLeft(text: string, i: number): boolean {
  if (i === 0) return true
  const prev = text[i - 1]
  return !/[A-Za-z0-9\u00C0-\u024F]/.test(prev)
}

function isUppercaseSentenceStart(ch: string): boolean {
  return /[A-Z\u00C4\u00D6\u00DC]/.test(ch)
}

// Whether `ch` is a Unicode letter — used to allow cuts before lowercase
// sentence starts (e.g. German articles like "die", "der", "ein").
function isLetter(ch: string): boolean {
  return /\p{L}/u.test(ch)
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

  constructor(mode: NarratorMode, supportsExpressiveMarkup: boolean) {
    this.mode = mode
    this.supportsExpressiveMarkup = supportsExpressiveMarkup
  }

  push(delta: string): SpeechSegment[] {
    if (!delta) return []
    this.buffer += delta
    const safeEnd = findSafeCutPoint(this.buffer, this.committedIndex, this.mode)
    if (safeEnd <= this.committedIndex) return []
    const chunk = this.buffer.slice(this.committedIndex, safeEnd)
    this.committedIndex = safeEnd
    return this.emitChunk(chunk)
  }

  flush(): SpeechSegment[] {
    if (this.committedIndex >= this.buffer.length) return []
    const rest = this.buffer.slice(this.committedIndex)
    this.committedIndex = this.buffer.length
    return this.emitChunk(rest)
  }

  reset(): void {
    this.buffer = ''
    this.committedIndex = 0
    this.wrapStack = []
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
