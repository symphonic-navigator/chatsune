# TTS Text Preprocessing Hardening — Design

**Date:** 2026-04-19
**Scope:** Frontend voice pipeline text preprocessing only
**Files touched:** `frontend/src/features/voice/pipeline/`

## Problem

Three observed issues when forwarding assistant text to TTS providers (xAI, Mistral):

1. **Ellipses are mangled.** The preprocessor collapses `...` (and the Unicode ellipsis `\u2026`) into a single `.`. The remaining `.` is then picked up as a sentence boundary, which breaks the cadence the author intended and truncates segments that should be one utterance.
2. **Markdown and quote decoration leaks through in the `off` mode** (and partly in `narrate` mode). Text such as `*he grinned*`, `_whispered_`, or `"hello"` reaches the TTS engine with its delimiters intact, which providers read aloud literally.
3. **Emojis are mishandled by providers.** xAI produces embarrassing audible artefacts; Mistral gets confused. Emojis carry no speakable value and should be stripped upstream.

## Goals

- Preserve `...` (and `\u2026` normalised to `...`) verbatim in the text sent to TTS; never treat the characters of an ellipsis as a sentence boundary.
- Strip `**bold**`, `__underline__`, `*italic*`, `_italic_` in **all** narrator modes, keeping the inner content.
- Strip `"…"` (straight and curly) in `off` mode only. In `play` / `narrate` mode these remain meaningful as voice-segment markers.
- Remove all emojis (including ZWJ sequences, regional-indicator flag pairs, and variation selectors) from the text sent to TTS.

## Non-Goals

- No change to the narrator segmentation contract (`play` / `narrate` splitting via `splitSegments` stays as-is).
- No refactor of the emoji-aware sentence-boundary logic in `streamingSentencer.ts` / `sentenceSplitter.ts`. After emojis are stripped from `preprocess`, the emoji branches in those regexes simply become dead paths — leaving them in place is cheaper than re-plumbing.
- No change to TTS provider adapters or backend code. The fix lives entirely in the frontend preprocessing layer.

## Design

### Affected files

| File | Purpose of change |
| --- | --- |
| `frontend/src/features/voice/pipeline/audioParser.ts` | Update `preprocess` (ellipse, markdown, quotes, emoji). Thread `mode` through `parseForSpeech` into `preprocess`. |
| `frontend/src/features/voice/pipeline/sentenceSplitter.ts` | Update `normaliseEllipses` and `SENTENCE_BOUNDARY` regex to keep ellipses intact and not split on them. |
| `frontend/src/features/voice/pipeline/streamingSentencer.ts` | In `findSafeCutPoint`, reject `.` as a cut candidate when preceded by another `.`. |

### Change 1 — Ellipses preserved and non-splitting

**`audioParser.ts` `preprocess`:**

- Remove `s.replace(/\.{2,}/g, '.')` (no more collapse).
- Replace `s.replace(/\u2026/g, '.')` with `s.replace(/\u2026/g, '...')` — normalise Unicode ellipsis to three ASCII dots so downstream logic sees one canonical form.

**`sentenceSplitter.ts` `normaliseEllipses`:**

- Drop the `\.{2,}` collapse.
- Keep `\u2026` → `...` (matches what `preprocess` now emits).

**`sentenceSplitter.ts` `SENTENCE_BOUNDARY` regex:**

Current:
```ts
/(?<=[.!?])(?:\s+(?=[A-Z\u00C4\u00D6\u00DC]|\p{Extended_Pictographic})|(?=\p{Extended_Pictographic}))/u
```

New:
```ts
/(?<![.][.])(?<=[.!?])(?:\s+(?=[A-Z\u00C4\u00D6\u00DC]|\p{Extended_Pictographic})|(?=\p{Extended_Pictographic}))/u
```

The added negative lookbehind `(?<![.][.])` rejects the match when the two characters preceding the current boundary candidate are both `.` — i.e. when the candidate is the third (or later) dot of an ellipsis. `.!` / `.?` / the first two dots of `...` are unaffected (their preceding two chars are not both `.`).

**`streamingSentencer.ts` `findSafeCutPoint`:**

Inside the `SENTENCE_END.test(ch)` branch (currently starting around line 92), add an early-continue:

```ts
if (ch === '.' && text[i - 1] === '.') continue
```

This makes the streaming sentencer refuse to commit on any `.` that is the second, third, or Nth dot of a run. The first dot is still handled by the existing logic, which refuses to cut unless followed by whitespace + uppercase / emoji — `...` fails that check because the next char is `.`, which is neither. So no single dot inside an ellipsis can trigger a commit.

### Change 2 — Markdown and quote decoration stripping

**`audioParser.ts` `preprocess` gains a `mode: NarratorMode` parameter.** `parseForSpeech` passes its existing `mode` argument through.

Inside `preprocess`, in the following order (so bold/underline don't leak into the single-delimiter patterns):

1. `**bold**` → inner content (already present).
2. `__underline__` → inner content (already present).
3. **New:** `*italic*` → inner content: `s.replace(/\*([^*\n]+)\*/g, '$1')`.
4. **New:** `_italic_` → inner content: `s.replace(/_([^_\n]+)_/g, '$1')`.
5. **New, gated on `mode === 'off'`:**
   - `"…"` → inner content: `s.replace(/"([^"\n]+)"/g, '$1')`.
   - `\u201c…\u201d` → inner content: `s.replace(/\u201c([^\u201d\n]+)\u201d/g, '$1')`.

Gating on `off` only is intentional: in `play` / `narrate` mode the quotes are voice-segment markers consumed by `splitSegments`.

**Interaction with `play` mode asterisk narration:** `play` mode used to rely on `*…*` as an explicit narration marker inside `splitSegments`. Stripping `*…*` in `preprocess` removes those markers before `splitSegments` runs, but the effect on the final output is identical: text outside quotes is already treated as narration, so `"Hello" *he smiled*` → `"Hello" he smiled` → same two segments as before.

### Change 3 — Emoji stripping

Add to `preprocess`, late enough that other regex cleanups still see their tokens:

```ts
s = s.replace(/\p{Extended_Pictographic}/gu, '')
s = s.replace(/\p{Regional_Indicator}/gu, '')
s = s.replace(/[\uFE0F\u200D]/g, '')
```

- `\p{Extended_Pictographic}` covers standard emoji code points.
- `\p{Regional_Indicator}` covers flag-emoji pairs (e.g. 🇩🇪).
- `\uFE0F` (variation selector-16) and `\u200D` (zero-width joiner) are swept up so orphaned joiners left by preceding replaces don't survive.

Skin-tone modifiers are already covered by `Extended_Pictographic` in modern Unicode tables.

### Test plan

Add cases to existing test files where possible:

- **`audioParser.test.ts`** (exists):
  - `"Hello... World"` in `off` mode round-trips with `...` intact and a single sentence.
  - `*whispered*` and `_emphasised_` lose their delimiters in `off` mode.
  - `"hello"` loses its quotes in `off` mode, keeps them as voice segment in `play` / `narrate` mode.
  - `"Hi 😀 there"` produces TTS text without the emoji.
  - `"🇩🇪 Guten Tag"` drops the flag.
  - In `play` mode: `"Hello" *he smiled*` still yields one voice segment and one narration segment.

- **`streamingSentencer.test.ts`** (exists):
  - Streaming `"Hello... World"` chunked across the ellipsis does not commit at the third dot.
  - `"Done. Next sentence."` still commits after the first `.` (regression check).

- **`sentenceSplitter`** either extend `audioParser.test.ts` or add a focused test file:
  - `"A... B"` → one sentence; `"A. B"` → two sentences.

All existing tests must continue to pass unchanged.

### Out of scope

- Strikethrough (`~~`), bullet lists, headings — already handled.
- Backticks and code fences — already handled.
- Smart apostrophes inside words — already protected by `isWordBoundaryLeft` in the sentencer.
