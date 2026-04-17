# Voice Sentence Streaming & Configurable Playback Gap

Date: 2026-04-17
Status: Design

## Summary

Split each speech segment into individual sentences and play them back
with a small, user-configurable gap between chunks. Mistral TTS produces
very clean boundaries, so back-to-back playback of long segments (or of
adjacent speaker turns in narrator mode) sounds unnaturally rushed. A
configurable inter-chunk pause, combined with sentence-level splitting,
gives the result a natural cadence and — as a side effect — shortens
time-to-first-audio, since only the first sentence has to be synthesised
before playback starts.

This builds directly on the centralised read-aloud state, cache-key
helper, and three-mode parser introduced by the
`2026-04-17-voice-auto-read-and-narrator-design` spec.

## Motivation

Two observations from first-hand testing of the narrator feature:

- Long quoted blocks (e.g. `"Hello there! How are you today?"`) are
  currently synthesised as a single TTS request. Time-to-first-audio is
  therefore bound by the full segment's synthesis latency.
- The transition from one speaker to another has no audible gap. Mistral's
  clean-edged output makes the handoff feel abrupt.

The fix is one mechanism with two benefits: split into sentences (faster
first-audio, finer-grained streaming) and insert a configurable delay
between chunks (natural cadence, clean speaker switches).

The gap setting belongs to the TTS integration, not the persona: it is
a property of how the engine renders endings, not of the character. Other
TTS engines added later may need different defaults; this keeps the
setting where the engine-specific knowledge lives.

## Non-Goals

- No per-mode or per-sentence vs per-speaker gap — one uniform gap value
  covers both cases.
- No toggle to disable sentence-streaming. Setting the gap to `0 ms`
  approximates the pre-feature behaviour closely enough; the added cost
  is extra TTS calls, which is acceptable.
- No parallel synthesis. Sentences are synthesised sequentially, one at
  a time. Parallel requests would complicate ordering, rate-limit
  handling, and error recovery for marginal latency gain.
- No prefetch/buffer-before-start strategy. Playback begins as soon as
  the first chunk is synthesised; if synthesis falls behind playback,
  the player simply waits for the next chunk.

## Design

### A. Sentence splitter

A new helper `splitSentences(text: string): string[]` encodes the
three-stage heuristic agreed during brainstorming:

1. **Ellipsis normalisation:** `/\.{2,}/g → '.'` and `/\u2026/g → '.'`.
   Catches typed `...`, typographic `…` (Autocorrect in macOS/iOS), and
   stylistic `....`. Applied as the first step so subsequent rules see a
   canonical form.
2. **Hard split at line breaks:** `text.split('\n')`. Lists (whose
   `- ` / `1. ` markers are already stripped in `preprocess`),
   enumerations, poetry, and multi-paragraph blocks all become separate
   chunks without extra logic.
3. **Soft split at sentence endings within a line:** match a `.`, `!`,
   or `?` followed by whitespace **and** an upper-case letter, or the
   end of the line. Pattern:
   `/([.!?])\s+(?=[A-Z\u00C4\u00D6\u00DC])|([.!?])$/`. The upper-case
   lookahead avoids splitting inside `Mr.`, `z. B.`, decimal numbers,
   and similar abbreviation-like sequences.

Splitting preserves the terminal punctuation with the sentence it
ended; the TTS reads the full `"Hello!"` rather than a bare `"Hello"`.
Trim + filter drops empty strings.

The function is pure and lives in `frontend/src/features/voice/pipeline/sentenceSplitter.ts`,
with matching tests in `__tests__/sentenceSplitter.test.ts`.

### B. Parser integration

`parseForSpeech(text, mode)` in `audioParser.ts` keeps its current
signature and mode-switching logic but applies `splitSentences` to the
text of every segment it would otherwise emit. One input segment may
therefore become one or more output segments of the same type
(`voice` stays `voice`, `narration` stays `narration`).

`off`-mode path: instead of `[{ type: 'voice', text: cleaned }]`, the
cleaned text goes through `splitSentences` and yields N `voice`
segments. Gap handling then works uniformly across all modes.

Ellipsis normalisation moves into `preprocess()` for consistency — the
splitter also runs it defensively, which is cheap and keeps the
splitter self-contained when called in isolation.

### C. Integration config field: `playback_gap_ms`

A new entry in the `mistral_voice` integration's `config_fields` list
(not `persona_config_fields`). The value is stored at
`user_integration_configs[<user>][mistral_voice].playback_gap_ms`.

Field descriptor:

- `key`: `"playback_gap_ms"`
- `label`: `"Pause between chunks"`
- `field_type`: `"select"`
- `options`: `[0, 50, 100, 200, 300, 500]` presented as `"0 ms"`, `"50 ms"`, etc.
- `required`: `false`
- `description`: `"Gap inserted between sentences and speaker switches. Mistral TTS produces crisp boundaries — a small pause sounds more natural."`
- **Default (when field missing from stored config):** `100`.

`select` was chosen over a new `number` field type to avoid adding a
form-widget variant just for one setting. The preset set covers the
useful range; fine-grained tuning is not a user need for this control.

The field appears automatically in the existing integration-config form
(`GenericConfigForm` already iterates `config_fields`), alongside the
API-key field. No new UI component is required.

### D. `audioPlayback` — stream closure and gap

Two focused changes in
`frontend/src/features/voice/infrastructure/audioPlayback.ts`:

1. **`streamClosed` flag + `closeStream()` method.** The current
   `onFinished` callback fires whenever the queue drains. That is
   correct today because the caller pushes everything synchronously
   before playback catches up. Under sentence-streaming, the queue can
   legitimately drain while synthesis is still running. Introduce:

   ```ts
   private streamClosed = false

   closeStream(): void {
     this.streamClosed = true
     // If queue is already empty and playback has stopped, fire onFinished now.
     if (!this.playing && this.queue.length === 0) {
       this.callbacks?.onFinished()
     }
   }
   ```

   `stopAll()` resets `streamClosed` to `false` for the next session.
   `playNext()` only fires `onFinished` when the queue is empty **and**
   `streamClosed === true`; otherwise it sets `this.playing = false`
   and waits for the next `enqueue`, which resumes playback.

2. **Inter-chunk gap.** The `setCallbacks` signature is extended:

   ```ts
   interface AudioPlaybackCallbacks {
     gapMs?: number
     onSegmentStart: (segment: SpeechSegment) => void
     onFinished: () => void
   }
   ```

   After `source.onended`, playback waits `gapMs` before calling
   `playNext()`:

   ```ts
   source.onended = () => {
     this.currentSource = null
     const gap = this.callbacks?.gapMs ?? 0
     if (gap > 0) {
       this.pendingGapTimer = setTimeout(() => this.playNext(), gap)
     } else {
       this.playNext()
     }
   }
   ```

   `stopAll()` clears any pending gap timer so cancellation is immediate.

### E. `ReadAloudButton` — stream closure + gap lookup

`runReadAloud` in `ReadAloudButton.tsx`:

- Reads the gap value from the active TTS integration's user config:

  ```ts
  const tts = ttsRegistry.active()
  const activeTTSDefn = /* … same as today … */
  const gapMs = ttsUserConfig?.playback_gap_ms as number | undefined ?? 100
  ```

  `ttsUserConfig` comes from `useIntegrationsStore().configs[ttsId].config`
  — the user-scoped integration config, parallel to the secrets store
  used for API keys.

- Passes `gapMs` into `audioPlayback.setCallbacks({ gapMs, onSegmentStart, onFinished })`.

- Calls `audioPlayback.closeStream()` once after the synthesis loop
  completes successfully (and at the end of the cache-hit branch,
  right after all `enqueue` calls). Cancellation paths
  (`activeMessageId !== messageId`, error catch) do not call
  `closeStream`; they rely on `stopAll()` which clears everything.

### F. Parser test coverage

Extend `audioParser.test.ts` to assert sentence-level output for all
three modes:

- `off` + multi-sentence input → N voice segments.
- `play` + `"Hi! Bye!" *nods*` → two voice segments and one narration
  segment.
- `narrate` + same input → inverted roles, still sentence-split.
- Ellipsis normalisation: `"Ich dachte... vielleicht sollte ich..."`
  produces a single chunk because each `.` is followed by a lower-case
  letter.
- Line-break split: bulleted list renders as one chunk per item.

`sentenceSplitter.test.ts` covers the splitter in isolation:

- Abbreviation safety: `"Mr. Smith went home."` → one sentence.
- Decimal numbers: `"It is 3.14 metres long."` → one sentence.
- Question / exclamation: `"Really? Yes!"` → two sentences.
- Unicode ellipsis → normalised.
- Empty string → empty array.

### G. Error paths

- **Single-sentence synthesis failure:** current behaviour is preserved —
  the error toast fires, `setActiveReader(null, 'idle')` resets state,
  `stopAll()` drains the queue. With streaming, failure mid-stream
  leaves the already-played sentences played; the user sees the error,
  state is clean.
- **Cache-hit branch:** splits are already baked into the cached
  segment list, so `closeStream()` after the last `enqueue` works
  identically to the fresh-synthesis path.

### H. Cache

Cache key is unchanged (`messageId:primary:narrator:mode`). Gap is a
playback-time property, not an audio property; existing cached
entries remain valid across gap changes. The number of chunks per
cache entry grows — from a small constant to roughly one per sentence —
but the total audio volume is identical, so memory impact is flat.

## Testing

### Automated

- Unit tests for `splitSentences` (see Section F).
- Existing `audioParser.test.ts` cases are updated to match the new
  per-sentence output. Cases that previously asserted a single-segment
  result for prose input now assert the equivalent sentence-level list.
- New test for `audioPlayback`: `closeStream()` called while queue has
  items defers `onFinished` until the queue drains; `closeStream()`
  called after queue is empty fires `onFinished` immediately.

### Manual

- Long quoted block (one sentence with multiple clauses): plays as a
  single chunk, gap only at the start and end.
- Multi-sentence quoted block: each sentence plays separately with a
  gap; time-to-first-audio is visibly shorter than before.
- Roleplay mode with two voices and multiple sentences per speaker:
  gap applies uniformly between sentences and between speaker switches.
- Markdown bullet list: each item plays as a separate chunk.
- Gap set to `0 ms`: playback behaviour matches pre-feature timing
  closely (back-to-back chunks).
- Gap set to `500 ms`: noticeable, theatrical pauses; still responsive.
- Stop during gap: clicking the active button during a pending gap
  timer cancels immediately.
- Ellipsis-heavy input (e.g. `"Ich dachte... vielleicht..."`): no
  spurious splits; plays as one fluid sentence with natural comma-like
  pauses from the TTS itself.

## Risks

- **Queue-drain mid-stream.** If synthesis is slower than playback, the
  player pauses, waits, and resumes. This is correct but produces an
  unintended gap longer than `gapMs`. In practice Mistral synthesis is
  fast enough to stay ahead for typical message lengths; if it turns
  out to be a recurring issue, the mitigation is prefetching the first
  N sentences before starting — deferred until we see the problem.
- **Abbreviation heuristic false positives.** The upper-case lookahead
  will split `"End. Ok."` (intended, correct) but also `"See Fig. A."`
  (not a sentence boundary, but harmless — "Fig" gets read as a tiny
  unit with a short pause, then "A" reads with another). Acceptable:
  the failure mode is one extra pause, not incorrect content. Full
  abbreviation dictionaries are out of scope.
- **Config field visibility.** The existing mistral_voice integration
  config UI must correctly render a `select`-typed field alongside the
  password-typed API key. `GenericConfigForm` already supports
  `select` fields (used for persona-level voice selection); the code
  path is shared but the config-level usage is new — worth a quick
  check during implementation.
