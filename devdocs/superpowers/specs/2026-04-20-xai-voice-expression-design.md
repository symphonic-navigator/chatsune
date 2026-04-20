# xAI Voice Expression — Design

**Status:** Draft · 2026-04-20
**Author:** Chris (with Claude)
**Supersedes:** —
**Related:** [2026-04-19 xAI voice integration](./2026-04-19-xai-voice-integration-design.md) · [2026-04-17 voice sentence streaming](./2026-04-17-voice-sentence-streaming-design.md) · [2026-04-17 voice auto-read and narrator](./2026-04-17-voice-auto-read-and-narrator-design.md)

---

## 1. Problem

The xAI TTS endpoint supports an expression markup dialect — inline tags
(`[pause]`, `[laugh]`, `[breath]`, …) for discrete sound events and
wrapping tags (`<whisper>…</whisper>`, `<emphasis>…</emphasis>`,
`<slow>…</slow>`, …) for prosodic modulation. These markups let the model
produce genuinely expressive speech, far beyond the neutral read-out that
current voice synthesis delivers.

Three things need to change to exploit this:

1. The LLM must learn the markup vocabulary and how to use it tastefully.
2. The sentence-by-sentence streaming TTS pipeline must keep wrapping-tag
   scope alive **across** sentence boundaries — a single wrap spanning
   three sentences must synthesise as three wrapped sentences.
3. The chat UI must render the markup visibly but unobtrusively, so the
   reader can see where the model made expressive choices, while prose
   flows normally around it.

## 2. Goals & non-goals

### Goals

- Teach the LLM about the xAI expression vocabulary whenever the
  `xai_voice` integration is enabled for the user, via the existing
  integration system-prompt extension mechanism.
- Preserve wrapping-tag scope across sentence splits in both the
  streaming pipeline and the manual read-aloud pipeline.
- Render canonical expression tags in the chat transcript as small
  inline monospace pills, outside code blocks, independent of the
  active TTS provider.
- Strip markup transparently for voice providers that do not advertise
  the new capability, so the user always hears something sensible even
  after a provider switch.
- Zero database migration — the feature is purely prompt, pipeline, and
  render surface.

### Non-goals

- Recovery logic for malformed or unclosed tags from the LLM. If the
  model writes `<whisper>` and never closes it within a message, the
  remaining segments are emitted with the tag still open; the state
  resets with the next message. This is the LLM's problem, not
  Chatsune's.
- Generalising the tag dialect across providers. Only xAI supports
  these specific tags; Mistral or future providers will have their own
  story if and when they need one.
- Per-persona opt-in for expressive voice. If the user has xAI voice
  enabled, expressive markup is always active — it is inherent to the
  provider's identity.
- Avatar hooks or lip-sync integration. The pill rendering leaves a
  clear DOM anchor (`.voice-tag` class) that future avatar work can
  read, but nothing in this spec wires that up.
- Backend-side sentence splitting. All splitting remains in the
  frontend voice pipeline.

## 3. Architecture overview

```
LLM output (text with tags)
    │
    ├─► Backend: system-prompt-template (xai_voice integration)
    │           teaches the model the vocabulary + dosage recipe
    │           + narrator-mode interaction rules
    │
    ▼
Frontend chat stream (delta events)
    │
    ├──► Chat rendering  (AssistantMessage → markdownComponents)
    │    └─► new rehypeVoiceTags plugin wraps canonical markers
    │        in .voice-tag pills, outside <code>/<pre> only
    │
    └──► TTS pipeline:
         │
         ├─► StreamingSentencer (per-message instance)
         │   - existing safe-cut logic unchanged
         │   - NEW: wrapStack carried as state across pushes
         │   - cut emits segment re-wrapped with entering+leaving stacks
         │
         ├─► audioParser.preprocess()
         │   - if active integration lacks TTS_EXPRESSIVE_MARKUP:
         │     strip inline tags and wrapping markers (keep content)
         │
         ├─► splitSegments (voice vs narration) — unchanged
         │
         └─► engine.synthesise() → xAI proxy / Mistral SDK / …
```

The manual read-aloud path shares the re-wrap logic but runs non-
incrementally: the entire message is processed in one pass, with the
same entering-stack/leaving-stack semantics applied at every sentence
boundary.

## 4. Canonical tag list (single source of truth)

Two sync-obligated files:

- `backend/modules/integrations/_voice_expression_tags.py` — Python
  constants plus `build_system_prompt_extension()`; consumed by
  `_registry.py` when declaring the `xai_voice` integration.
- `frontend/src/features/voice/expressionTags.ts` — TS constants plus
  pre-compiled regexes; consumed by `streamingSentencer`, `audioParser`,
  `sentenceSplitter`, and `rehypeVoiceTags`.

Inline tags (carry their own content, no wrapping):

```
pause, long-pause, hum-tune,
laugh, chuckle, giggle, cry,
tsk, tongue-click, lip-smack,
breath, inhale, exhale, sigh
```

Wrapping tags (require open + close, wrap arbitrary content):

```
soft, whisper, loud, build-intensity, decrease-intensity,
higher-pitch, lower-pitch, slow, fast,
sing-song, singing, laugh-speak, emphasis
```

`CLAUDE.md` gains a short section "xAI Voice Expression Tags" pointing
at both files and stating the sync obligation. No runtime drift check —
the list changes rarely enough that documentation is the right place
for the guard.

Unknown tags (anything not in the canonical list) are treated as plain
text in every stage: the sentencer does not push them on the stack,
the filter does not strip them, the renderer does not pill them.

## 5. Backend changes

### 5.1 Capability flag

`shared/dtos/integrations.py`:

```python
class IntegrationCapability(str, Enum):
    ...
    TTS_EXPRESSIVE_MARKUP = "tts_expressive_markup"
```

The capability is declarative metadata on the integration definition.
The frontend reads it via the existing integrations config DTO to
decide whether to strip markup before synthesis.

### 5.2 xAI registration

`backend/modules/integrations/_registry.py` — the `xai_voice`
integration definition gains the new capability alongside its existing
`TTS_PROVIDER` and `STT_PROVIDER`, and its `system_prompt_template`
becomes the output of `build_system_prompt_extension()`.

`mistral_voice` is not touched.

### 5.3 System-prompt extension content

Generated by `build_system_prompt_extension()` and enclosed in
`<integrations name="xai_voice">…</integrations>` per the convention
established by the `lovense` integration.

The extension has five sections:

1. **Capability announcement** — one sentence establishing that the
   TTS provider interprets expression markup.
2. **Tag vocabulary** — the canonical list grouped by category (pauses,
   laughter, mouth sounds, breathing, volume, pitch, speed, style) with
   a one-line description per tag.
3. **Syntax** — inline in square brackets, wrapping in angle brackets,
   nesting allowed.
4. **Dosage recipe** — typically zero to two markups per message; use
   for genuine emphasis, not decoration; the TTS sounds natural when
   markup is rare.
5. **Narrator-mode interaction** — when writing dialogue inside
   `"…"`, placing a wrapping tag inside the quotes applies only to the
   dialogue voice; placing it outside applies to both narration and
   dialogue. Avoid overlaps that straddle dialogue and narration
   unnecessarily.

No negative examples. Strong models tend to mimic them rather than
avoid them.

### 5.4 What does not change on the backend

- The voice HTTP proxy route (`_handlers.py:185-203`) is unchanged;
  tags travel in the existing `text` field.
- `XaiVoiceAdapter.synthesise()` is unchanged; the xAI TTS endpoint
  accepts markup in `text` natively.
- No new Pydantic models beyond the enum value.
- No MongoDB changes, no event changes, no migration.

## 6. Frontend: streaming pipeline

### 6.1 StreamingSentencer — wrapping tag stack

`frontend/src/features/voice/pipeline/streamingSentencer.ts` gains a
`wrapStack: string[]` field, persisted across `push()` calls and
cleared on `reset()`.

The existing `findSafeCutPoint` scanner, which today tracks balanced
constructs (code fences, inline code, OOC markers, quotes, asterisk
italics) and refuses to cut inside unbalanced ones, is extended to
also recognise canonical wrapping tags — but with a crucial difference
in semantics:

> **Wrapping tags are state, not a balance check.**
> An unbalanced wrap must not block a cut. The cut proceeds at the
> first syntactically safe sentence boundary for the existing balanced
> constructs, regardless of whether the wrap stack is empty.

When a cut at `cutPoint` is committed, the emit logic re-wraps the
extracted segment:

1. Record the `enteringStack` — the snapshot of the persistent
   `wrapStack` at segment start.
2. Initialise a working stack as a copy of `enteringStack`.
3. Scan the segment; every canonical `<tag>` pushes onto the working
   stack, every `</tag>` pops. Unknown tags and underflow pops
   (a `</tag>` with an empty stack or a non-matching top) are ignored
   — the text is passed through verbatim, the LLM owns that mistake.
4. Compute the `leavingStack` — the working stack after scanning the
   whole segment.
5. Compute the emitted text:
   - Prepend `<tag>` for each tag in `enteringStack` (stack order).
   - Keep the segment text as-is, tags included.
   - Append `</tag>` for each tag in `leavingStack` (reverse stack
     order).
6. Update the persistent `wrapStack` to `leavingStack`.

This is symmetrical and reconstructs the scope on both ends, so each
emitted segment is self-contained at the TTS provider.

**Example walk-through.** Buffer after first push: `<whisper>ich
verrate dir ein geheimnis. die klingonen`. Sentence boundary after
`geheimnis.` — cut commits there.

- `enteringStack`: `[]`
- segment text: `<whisper>ich verrate dir ein geheimnis.`
- scanning pushes `whisper`; nothing pops
- `leavingStack`: `["whisper"]`
- emitted: `<whisper>ich verrate dir ein geheimnis.</whisper>`
- persistent `wrapStack` becomes `["whisper"]`

Second push adds `planen einen angriff.</whisper>`. Cut after
`angriff.`.

- `enteringStack`: `["whisper"]`
- segment text: `planen einen angriff.</whisper>`
- scanning pops `whisper`
- `leavingStack`: `[]`
- emitted: `<whisper>planen einen angriff.</whisper>`
- persistent `wrapStack` becomes `[]`

**Nested example.** `<soft><emphasis>wichtig.</emphasis> nicht so
wichtig.</soft>` with a cut after `wichtig.`:

- segment 1: `<soft><emphasis>wichtig.</emphasis>` →
  `leavingStack = ["soft"]` → emit as-is plus `</soft>` →
  `<soft><emphasis>wichtig.</emphasis></soft>`
- segment 2: ` nicht so wichtig.</soft>` with
  `enteringStack = ["soft"]` →
  `<soft> nicht so wichtig.</soft>` → `leavingStack = []`

**Unclosed at message end.** If `flush()` is called with a non-empty
persistent `wrapStack`, the remaining buffer is emitted with the
entering stack prepended but no synthetic closes appended. The xAI
API handles what it gets; the next message starts with a fresh
sentencer and an empty stack.

### 6.2 audioParser — conditional strip

`frontend/src/features/voice/pipeline/audioParser.ts` — `preprocess()`
gains a `supportsExpressiveMarkup: boolean` argument (default `false`
to keep call sites that do not yet know about the capability safe).

When the flag is `false`, a new pre-step runs before the existing
preprocessing chain:

- Remove every canonical inline tag and its surrounding brackets
  (`[pause]` → vanishes entirely).
- Remove every canonical wrapping tag marker (`<whisper>` and
  `</whisper>` vanish; the content between them is kept).

When the flag is `true`, the pre-step is skipped and tags survive
intact through the rest of the chain (which does not touch `[…]`,
`<…>`, or `</…>` in its current form, so no further conflict).

The flag is resolved per synthesis call by looking up the persona's
active TTS provider, finding the integration definition, and checking
its `capabilities` array. This lives at the call-site in
`ReadAloudButton` / streaming auto-read session, which already know
the persona and provider. A small helper in `features/voice/` exposes
`providerSupportsExpressiveMarkup(integrationId) → boolean`.

### 6.3 Manual read-aloud path

`frontend/src/features/voice/pipeline/sentenceSplitter.ts` does not
maintain streaming state, but it must apply the same re-wrap
semantics when the user clicks Read on a complete message.

A new helper — `wrapSegmentWithActiveStack(text, entering, leaving)` —
is shared between the streaming and manual paths. The manual splitter
walks the message once, maintaining a working stack initialised empty,
and at each sentence boundary emits the preceding segment re-wrapped
against the stack snapshots at segment start and end.

### 6.4 splitSegments (voice vs narration) — also wrap-aware

After preprocess runs, `splitSegments()` in `audioParser.ts` splits
the text into voice (quoted) and narration (unquoted) pieces. A
sentence-level segment may contain both a wrap and a quote:

```
<whisper>er sagte "hallo welt" gestern.</whisper>
```

A naive quote split would produce three unbalanced pieces. Since §6.1
produces sentence-level segments that are self-contained, the quote
split must **preserve that property** within each sub-segment.

The same `wrapSegmentWithActiveStack` helper is used: `splitSegments`
walks the text character by character, maintaining a working wrap
stack in parallel to the quote-depth tracker. At each quote-in or
quote-out transition, it emits the preceding sub-segment re-wrapped
against the wrap-stack snapshots at sub-segment start and end.

For the example above, the output is:

```
narration: <whisper>er sagte </whisper>
voice:     <whisper>hallo welt</whisper>
narration: <whisper> gestern.</whisper>
```

Each piece is independently synthesisable. The narrator voice whispers
the narration, the dialogue voice whispers the dialogue — the outcome
promised by §4's decision.

For xAI-capable providers the whispers propagate correctly. For
providers without the capability, the markup is already gone at this
stage (stripped by preprocess in §6.2), so `splitSegments` sees plain
text and behaves identically to today.

## 7. Frontend: chat rendering

### 7.1 rehypeVoiceTags plugin

New file: `frontend/src/features/chat/rehypeVoiceTags.ts`.

A rehype plugin that traverses the HAST produced by
`react-markdown` + `remark-gfm`, and splits text nodes that contain
canonical tag markers into a sequence of text nodes and
`<span class="voice-tag">…</span>` nodes.

The plugin's per-node contract:

- If the text node's ancestor chain includes a `code` or `pre` element,
  return the node unchanged. This covers fenced code blocks, inline
  code, and any plugin output that renders as `<code>` (Mermaid and
  KaTeX render differently and do not expose text nodes at this level).
- Otherwise, run a single combined regex against the text. The regex
  matches either a canonical inline tag `[tag]` or a canonical wrapping
  marker `<tag>` / `</tag>`.
- For each match, split the text node into: text before, a
  `voice-tag` span containing the literal match, text after. Iterate.

The span contains the literal tag text: `[laugh]`, `<whisper>`,
`</whisper>`. The content between a pair of wrapping markers is not
altered — adjacent markdown (bold, italic, links) continues to render
normally around it.

### 7.2 Styling

New CSS class `.voice-tag` registered alongside existing chat prose
styles:

```css
.voice-tag {
  font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
  font-size: 0.75em;
  padding: 0.05em 0.3em;
  margin: 0 0.1em;
  border-radius: 0.25em;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.6);
  vertical-align: 0.05em;
}
```

The font stack matches the codebase convention (already in use via
Tailwind's `font-mono` class and in `frontend/src/index.css`).

The colour and opacity values are subtle on both the opulent
user-facing theme and the Catppuccin admin theme. The class is the
DOM anchor that future avatar work can target.

### 7.3 Streaming render

`react-markdown` re-parses the message on every streaming delta. The
rehype plugin therefore runs on every token. No special handling is
needed for half-received tags: an incomplete `<whis` is not matched
by the regex and renders as plain text; as soon as the `per>` arrives,
the next re-render pills it.

Unclosed wrapping tags pill only the opener; the prose flows
afterwards without a visual scope marker. That is the intentional
behaviour from §2 non-goals — we do not synthesise what the LLM did
not write.

## 8. Testing

### 8.1 Automated

**Frontend — Vitest.**

`streamingSentencer.test.ts` additions:

- A wrap opens before a sentence end and closes after → two emissions,
  each wrapped (the canonical example).
- Nested wraps crossing a sentence boundary → both layers reconstructed
  on both sides of the cut.
- Inline tag split across chunk boundary (`[lau` + `gh]`) → emitted
  intact in one segment.
- Unknown tag `<foo>` in prose → passes through as plain text, no
  stack push.
- Flush with non-empty stack → final segment emitted with opening
  wraps from the stack but no synthetic closes.
- Wrap entirely inside a quote in narrate mode → scoping still
  correct when `splitSegments` later classifies.

`audioParser.test.ts` additions:

- `supportsExpressiveMarkup = false` with inline and wrapping tags
  in the text → tags gone, surrounding content intact.
- `supportsExpressiveMarkup = true` → tags survive preprocess.
- Existing code-block strip already removes tag-lookalikes inside
  fences; one verification test documents the interaction.
- `splitSegments` wrap-awareness: input `<whisper>er sagte "hallo
  welt" gestern.</whisper>` in narrate mode → three sub-segments, each
  independently wrapped in `<whisper>…</whisper>`.
- `splitSegments` with wrap fully inside a quote: `er sagte
  "<whisper>hallo</whisper>"` → only the voice sub-segment carries
  the wrap; surrounding narration is plain.

`rehypeVoiceTags.test.ts`:

- Tag in prose → text / pill / text sequence.
- Tag inside inline code → untouched.
- Tag next to bold/italic → pill plus bold text rendered correctly.

**Backend — pytest.**

- `test_voice_expression_tags.py`: every canonical tag appears in the
  generated system-prompt extension; the narrator-mode section and
  dosage recipe are present; the output is wrapped in the
  `<integrations name="xai_voice">` frame.
- `test_registry.py` extension: `xai_voice` integration advertises
  `TTS_EXPRESSIVE_MARKUP`; `mistral_voice` does not.

### 8.2 Manual verification (pre-merge)

1. Persona configured with xAI voice, streaming auto-read active. Send
   a message that provokes a `<whisper>…</whisper>` spanning two or
   three sentences. Confirm: the whisper is audible in every
   sentence, pills render in the transcript, no audio glitches at
   sentence boundaries.
2. Same persona reconfigured to Mistral voice. Same provoking
   message. Confirm: transcript still pills the tags, TTS speaks the
   content without the markup literally pronounced.
3. Open an older message that contains tags, with xAI voice
   integration disabled. Confirm: pills still render.
4. Click Read on a multi-sentence wrapped message. Confirm: the
   manual path re-wraps the same way streaming does.
5. Fenced code block containing `<whisper>test</whisper>`. Confirm:
   no pills inside the code block.
6. Narrate mode, dialogue in quotes inside a `<whisper>` that spans
   narration and dialogue. Confirm: both voices whisper.

### 8.3 Explicit non-tests

- No end-to-end test against the real xAI endpoint (flaky, key-bound).
- No malformed-tag recovery tests (behaviour is undefined on purpose).
- No sync check between the Python and TS canonical tag files (docs
  are the guard).

## 9. Risks and mitigations

- **Model over-tags.** The dosage recipe in the prompt is the first
  defence. If empirical usage is still too heavy, the recipe is
  plain prose and can be sharpened without code changes.
- **Pill visual overcrowding.** At two markups per message the pills
  read as light accents; at ten they crowd. The response is to
  sharpen the dosage recipe, not adjust the renderer.
- **rehypeVoiceTags perf on long messages.** The plugin walks every
  text node on every streaming render. A cheap early-exit (substring
  `.includes(']')` / `.includes('>')` before regex) can be added if
  measurement warrants; it is not in the initial implementation.
- **Canonical list drift between Python and TS.** Only the
  `CLAUDE.md` note and code-review discipline. Acceptable because the
  list changes rarely and drift is visible (a new tag not in the
  prompt simply does not appear; a removed tag not yet stripped is
  harmless).
- **Provider switch mid-stream.** If the user switches the persona's
  TTS provider while a message is streaming, already-synthesised
  segments reflect the old provider's capability; subsequent segments
  reflect the new one. Inconsistent playback for that single message,
  but no failure. Accepted.

## 10. Rollout

No feature flag, no staged rollout. The change lands as one PR on
`master`. The user can disable the behaviour in practice by not
enabling the `xai_voice` integration — existing personas using Mistral
are unaffected because the system prompt is only injected when the
user has the xAI integration enabled.

No data migration, no backfill, no coordinated deploy between backend
and frontend beyond the normal atomic master push.
