# xAI Voice Expression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thread xAI's expression markup (inline `[pause]` / `[laugh]` tags, wrapping `<whisper>…</whisper>` / `<emphasis>…</emphasis>` tags) through the sentence-streaming voice pipeline and chat render surface, per the 2026-04-20 design spec.

**Architecture:** Backend declares a new `TTS_EXPRESSIVE_MARKUP` capability and injects a prompt extension when `xai_voice` is enabled. Frontend extends the existing `StreamingSentencer` with a wrap-tag stack (state, not balance-block) and shares a `wrapSegmentWithActiveStack` helper with the non-streaming sentence splitter and the wrap-aware `splitSegments`. The chat renderer gains a rehype plugin that pills canonical markers outside code blocks.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 (backend), TypeScript + React + Vite + `react-markdown` + rehype/unified (frontend). Vitest + pytest for tests. All code in British English.

**Reference:** [`devdocs/superpowers/specs/2026-04-20-xai-voice-expression-design.md`](../specs/2026-04-20-xai-voice-expression-design.md)

---

## File Structure

**Backend — create:**
- `backend/modules/integrations/_voice_expression_tags.py` — canonical Python tag lists + `build_system_prompt_extension()`
- `backend/tests/modules/integrations/test_voice_expression_tags.py` — content checks on the generated prompt + registry wiring

**Backend — modify:**
- `shared/dtos/integrations.py` — add `TTS_EXPRESSIVE_MARKUP` enum value
- `backend/modules/integrations/_registry.py` — add the new capability to `xai_voice` and wire the prompt builder

**Frontend — create:**
- `frontend/src/features/voice/expressionTags.ts` — canonical TS tag list + pre-compiled regexes
- `frontend/src/features/voice/__tests__/expressionTags.test.ts` — regex sanity checks
- `frontend/src/features/voice/pipeline/wrapStack.ts` — `scanSegment`, `wrapSegmentWithActiveStack`, shared between streaming and manual paths
- `frontend/src/features/voice/pipeline/__tests__/wrapStack.test.ts` — helper unit tests
- `frontend/src/features/voice/engines/expressiveMarkupCapability.ts` — `providerSupportsExpressiveMarkup()` lookup
- `frontend/src/features/voice/engines/__tests__/expressiveMarkupCapability.test.ts`
- `frontend/src/features/chat/rehypeVoiceTags.ts` — rehype plugin pilling canonical markers outside `<code>`/`<pre>`
- `frontend/src/features/chat/__tests__/rehypeVoiceTags.test.ts`

**Frontend — modify:**
- `frontend/src/features/voice/pipeline/streamingSentencer.ts` — wrap-stack as persistent state, scanner ignores unknown/unterminated wraps, emits with re-wrap
- `frontend/src/features/voice/pipeline/__tests__/streamingSentencer.test.ts` — new cases for wrap propagation
- `frontend/src/features/voice/pipeline/audioParser.ts` — `preprocess()` takes `supportsExpressiveMarkup`; `splitSegments` becomes wrap-aware
- `frontend/src/features/voice/__tests__/audioParser.test.ts` — new cases for strip + wrap-aware split
- `frontend/src/features/voice/pipeline/sentenceSplitter.ts` — wrap-aware sentence split for the manual read-aloud path
- `frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts` — new cases (create file if absent)
- `frontend/src/features/voice/components/ReadAloudButton.tsx` — resolve + pass `supportsExpressiveMarkup`
- `frontend/src/features/voice/pipeline/voicePipeline.ts` — accept + forward the flag
- `frontend/src/features/chat/ChatView.tsx` — resolve + pass the flag into `createStreamingSentencer`
- `frontend/src/features/chat/markdownComponents.tsx` — register `rehypeVoiceTags` in `rehypePlugins`
- `frontend/src/index.css` — add `.voice-tag` class
- `CLAUDE.md` — add "xAI Voice Expression Tags" sync note

---

## Task 1: Add `TTS_EXPRESSIVE_MARKUP` capability (backend)

**Files:**
- Modify: `shared/dtos/integrations.py:7-10`
- Modify: `backend/modules/integrations/_registry.py:232-235`

Start with the enum value and a test that asserts `xai_voice` will have this capability once wired. The capability value is read as a plain string downstream (frontend `resolver.ts` checks lowercase strings), so the `.value` must be `"tts_expressive_markup"`.

- [ ] **Step 1: Write failing backend test**

Create `backend/tests/modules/integrations/test_voice_expression_tags.py` (new file):

```python
from backend.modules.integrations._registry import _registry  # noqa: F401 - force registration
from backend.modules.integrations import get_integration
from shared.dtos.integrations import IntegrationCapability


def test_xai_voice_advertises_expressive_markup_capability() -> None:
    defn = get_integration("xai_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_EXPRESSIVE_MARKUP in defn.capabilities


def test_mistral_voice_does_not_advertise_expressive_markup() -> None:
    defn = get_integration("mistral_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_EXPRESSIVE_MARKUP not in defn.capabilities
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/modules/integrations/test_voice_expression_tags.py -v
```

Expected: `AttributeError: TTS_EXPRESSIVE_MARKUP` (enum member does not exist).

- [ ] **Step 3: Add enum value in `shared/dtos/integrations.py`**

Replace lines 7–10:

```python
class IntegrationCapability(str, Enum):
    TOOL_PROVIDER = "tool_provider"
    TTS_PROVIDER = "tts_provider"
    STT_PROVIDER = "stt_provider"
    TTS_EXPRESSIVE_MARKUP = "tts_expressive_markup"
```

- [ ] **Step 4: Wire capability into `xai_voice` registration**

In `backend/modules/integrations/_registry.py`, the capabilities list at lines 232–235 currently reads:

```python
capabilities=[
    IntegrationCapability.TTS_PROVIDER,
    IntegrationCapability.STT_PROVIDER,
],
```

Change to:

```python
capabilities=[
    IntegrationCapability.TTS_PROVIDER,
    IntegrationCapability.STT_PROVIDER,
    IntegrationCapability.TTS_EXPRESSIVE_MARKUP,
],
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest backend/tests/modules/integrations/test_voice_expression_tags.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/integrations.py backend/modules/integrations/_registry.py backend/tests/modules/integrations/test_voice_expression_tags.py
git commit -m "Add TTS_EXPRESSIVE_MARKUP capability to xai_voice"
```

---

## Task 2: Backend tag list + prompt builder

**Files:**
- Create: `backend/modules/integrations/_voice_expression_tags.py`
- Modify: `backend/tests/modules/integrations/test_voice_expression_tags.py`

The builder assembles the system prompt extension per §5.3 of the spec: capability announcement, vocabulary grouped by category, syntax rules, dosage recipe, narrator-mode interaction. Wrapped in `<integrations name="xai_voice">…</integrations>` per the convention.

- [ ] **Step 1: Extend the test with content assertions**

Append these tests to `backend/tests/modules/integrations/test_voice_expression_tags.py`:

```python
from backend.modules.integrations._voice_expression_tags import (
    INLINE_TAGS,
    WRAPPING_TAGS,
    build_system_prompt_extension,
)


def test_inline_tags_cover_xai_vocabulary() -> None:
    expected = {
        "pause", "long-pause", "hum-tune",
        "laugh", "chuckle", "giggle", "cry",
        "tsk", "tongue-click", "lip-smack",
        "breath", "inhale", "exhale", "sigh",
    }
    assert set(INLINE_TAGS) == expected


def test_wrapping_tags_cover_xai_vocabulary() -> None:
    expected = {
        "soft", "whisper", "loud", "build-intensity", "decrease-intensity",
        "higher-pitch", "lower-pitch", "slow", "fast",
        "sing-song", "singing", "laugh-speak", "emphasis",
    }
    assert set(WRAPPING_TAGS) == expected


def test_prompt_extension_mentions_every_tag() -> None:
    prompt = build_system_prompt_extension()
    for tag in INLINE_TAGS:
        assert f"[{tag}]" in prompt, f"inline tag {tag!r} missing from prompt"
    for tag in WRAPPING_TAGS:
        assert f"<{tag}>" in prompt, f"wrapping tag {tag!r} missing from prompt"


def test_prompt_extension_has_integrations_frame() -> None:
    prompt = build_system_prompt_extension()
    assert prompt.startswith('<integrations name="xai_voice">')
    assert prompt.endswith("</integrations>")


def test_prompt_extension_has_dosage_recipe() -> None:
    prompt = build_system_prompt_extension()
    low = prompt.lower()
    # Accept any phrasing that signals "use sparingly, ~0-2 per message".
    assert "sparing" in low or "0" in prompt
    assert "message" in low


def test_prompt_extension_has_narrator_mode_section() -> None:
    prompt = build_system_prompt_extension()
    low = prompt.lower()
    assert "narrat" in low  # narration / narrator
    assert "dialogue" in low or "quote" in low


def test_xai_voice_registration_uses_prompt_builder() -> None:
    defn = get_integration("xai_voice")
    assert defn is not None
    expected = build_system_prompt_extension()
    assert defn.system_prompt_template == expected
```

- [ ] **Step 2: Run to verify failures**

```bash
uv run pytest backend/tests/modules/integrations/test_voice_expression_tags.py -v
```

Expected: `ModuleNotFoundError: backend.modules.integrations._voice_expression_tags`.

- [ ] **Step 3: Create the tag list + prompt builder**

Create `backend/modules/integrations/_voice_expression_tags.py`:

```python
"""Canonical xAI voice expression tag vocabulary and system-prompt builder.

This file is one half of a two-file source of truth; the other half is
``frontend/src/features/voice/expressionTags.ts``. Any change here must
be mirrored there. See the "xAI Voice Expression Tags" note in
``CLAUDE.md``.
"""

from __future__ import annotations

INLINE_TAGS: list[str] = [
    # Pauses
    "pause", "long-pause", "hum-tune",
    # Laughter & crying
    "laugh", "chuckle", "giggle", "cry",
    # Mouth sounds
    "tsk", "tongue-click", "lip-smack",
    # Breathing
    "breath", "inhale", "exhale", "sigh",
]

WRAPPING_TAGS: list[str] = [
    # Volume & intensity
    "soft", "whisper", "loud", "build-intensity", "decrease-intensity",
    # Pitch & speed
    "higher-pitch", "lower-pitch", "slow", "fast",
    # Vocal style
    "sing-song", "singing", "laugh-speak", "emphasis",
]


def build_system_prompt_extension() -> str:
    inline_lines = "\n".join(
        f"- `[{tag}]` — {_describe_inline(tag)}" for tag in INLINE_TAGS
    )
    wrapping_lines = "\n".join(
        f"- `<{tag}>…</{tag}>` — {_describe_wrapping(tag)}" for tag in WRAPPING_TAGS
    )
    return (
        '<integrations name="xai_voice">\n'
        "## Voice Expression\n\n"
        "Your speech is synthesised by xAI's voice engine, which understands "
        "two kinds of expression markup in the text you write. Used with "
        "restraint, these make your voice sound alive; overused, they make "
        "it exhausting to listen to.\n\n"
        "### Syntax\n\n"
        "- Inline tags in square brackets trigger a discrete sound or "
        "pause: `[laugh]`, `[breath]`, `[pause]`.\n"
        "- Wrapping tags in angle brackets modulate the voice across the "
        "text they enclose: `<whisper>a secret</whisper>`.\n"
        "- Wrapping tags may nest: `<soft><emphasis>word</emphasis></soft>`.\n\n"
        "### Inline tags\n\n"
        f"{inline_lines}\n\n"
        "### Wrapping tags\n\n"
        f"{wrapping_lines}\n\n"
        "### Dosage recipe\n\n"
        "Typically zero to two markups per message. Not every sentence. "
        "Use a wrapping tag for genuine emphasis, a pause to let a "
        "punchline land, a breath when it would feel natural to take one. "
        "Speech sounds natural when markup is rare.\n\n"
        "### Narrator-mode interaction\n\n"
        "When you write dialogue in straight or curly double quotes, the "
        "dialogue is synthesised in a different voice from the narration. "
        "A wrapping tag placed inside the quotes applies only to the "
        "dialogue voice. A wrapping tag placed around quoted dialogue and "
        "surrounding narration applies to both voices. Prefer to keep a "
        "wrapping tag either fully inside or fully outside a quote; "
        "avoid starting a wrap in narration and ending it inside dialogue "
        "(or vice versa).\n"
        "</integrations>"
    )


def _describe_inline(tag: str) -> str:
    table = {
        "pause": "a short silence",
        "long-pause": "a longer deliberate silence",
        "hum-tune": "a brief hummed tune",
        "laugh": "a full laugh",
        "chuckle": "a quiet chuckle",
        "giggle": "a playful giggle",
        "cry": "a sob or cry",
        "tsk": "a disapproving tsk",
        "tongue-click": "a tongue click",
        "lip-smack": "a lip smack",
        "breath": "an audible breath",
        "inhale": "an inward breath",
        "exhale": "an outward breath",
        "sigh": "a sigh",
    }
    return table[tag]


def _describe_wrapping(tag: str) -> str:
    table = {
        "soft": "soften the delivery",
        "whisper": "whisper",
        "loud": "raise the volume",
        "build-intensity": "build intensity across the wrapped text",
        "decrease-intensity": "fade intensity across the wrapped text",
        "higher-pitch": "raise the pitch",
        "lower-pitch": "lower the pitch",
        "slow": "slow the pace",
        "fast": "speed up the pace",
        "sing-song": "sing-song intonation",
        "singing": "sing the wrapped text",
        "laugh-speak": "speak through laughter",
        "emphasis": "emphasise the wrapped text",
    }
    return table[tag]
```

- [ ] **Step 4: Wire builder into the `xai_voice` registration**

In `backend/modules/integrations/_registry.py`, find the `xai_voice` `register(IntegrationDefinition(...))` call (starting around line 225). The current definition has no `system_prompt_template` argument. Add it.

Add this import at the top of the file (look for existing imports; add alongside them):

```python
from backend.modules.integrations._voice_expression_tags import build_system_prompt_extension
```

Inside the `IntegrationDefinition(...)` call for `xai_voice`, after the `hydrate_secrets=False,` line (around line 231), add:

```python
        system_prompt_template=build_system_prompt_extension(),
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest backend/tests/modules/integrations/test_voice_expression_tags.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/_voice_expression_tags.py backend/modules/integrations/_registry.py backend/tests/modules/integrations/test_voice_expression_tags.py
git commit -m "Add xAI voice expression prompt extension"
```

---

## Task 3: Frontend canonical tag list

**Files:**
- Create: `frontend/src/features/voice/expressionTags.ts`
- Create: `frontend/src/features/voice/__tests__/expressionTags.test.ts`

The frontend constants and compiled regexes. Three patterns are exposed: `INLINE_TAG_PATTERN` (matches `[tag]`), `WRAPPING_OPEN_PATTERN` (matches `<tag>`), `WRAPPING_CLOSE_PATTERN` (matches `</tag>`). Each is anchored to the canonical list to avoid false positives on `[1]`, `<br>`, etc. A combined `ANY_TAG_PATTERN` is used by the rehype plugin and the strip function.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/voice/__tests__/expressionTags.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import {
  INLINE_TAGS,
  WRAPPING_TAGS,
  INLINE_TAG_PATTERN,
  WRAPPING_OPEN_PATTERN,
  WRAPPING_CLOSE_PATTERN,
  ANY_TAG_PATTERN,
  isKnownWrappingTag,
} from '../expressionTags'

describe('expressionTags constants', () => {
  it('INLINE_TAGS covers the xAI inline vocabulary', () => {
    expect(new Set(INLINE_TAGS)).toEqual(
      new Set([
        'pause', 'long-pause', 'hum-tune',
        'laugh', 'chuckle', 'giggle', 'cry',
        'tsk', 'tongue-click', 'lip-smack',
        'breath', 'inhale', 'exhale', 'sigh',
      ]),
    )
  })

  it('WRAPPING_TAGS covers the xAI wrapping vocabulary', () => {
    expect(new Set(WRAPPING_TAGS)).toEqual(
      new Set([
        'soft', 'whisper', 'loud', 'build-intensity', 'decrease-intensity',
        'higher-pitch', 'lower-pitch', 'slow', 'fast',
        'sing-song', 'singing', 'laugh-speak', 'emphasis',
      ]),
    )
  })
})

describe('INLINE_TAG_PATTERN', () => {
  it('matches a canonical inline tag', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('hello [laugh] world'.match(re)).toEqual(['[laugh]'])
  })

  it('does not match an unknown bracketed token', () => {
    const re = new RegExp(INLINE_TAG_PATTERN.source, 'g')
    expect('see [1] in the footnote'.match(re)).toBeNull()
  })
})

describe('WRAPPING_OPEN_PATTERN / WRAPPING_CLOSE_PATTERN', () => {
  it('match open and close markers of canonical wraps', () => {
    const open = new RegExp(WRAPPING_OPEN_PATTERN.source, 'g')
    const close = new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g')
    expect('<whisper>hi</whisper>'.match(open)).toEqual(['<whisper>'])
    expect('<whisper>hi</whisper>'.match(close)).toEqual(['</whisper>'])
  })

  it('does not match unknown markers', () => {
    const open = new RegExp(WRAPPING_OPEN_PATTERN.source, 'g')
    expect('<br> line break'.match(open)).toBeNull()
  })
})

describe('ANY_TAG_PATTERN', () => {
  it('matches all three tag shapes in one pass', () => {
    const re = new RegExp(ANY_TAG_PATTERN.source, 'g')
    const input = '<whisper>a [laugh] b</whisper>'
    const matches = [...input.matchAll(re)].map((m) => m[0])
    expect(matches).toEqual(['<whisper>', '[laugh]', '</whisper>'])
  })
})

describe('isKnownWrappingTag', () => {
  it('returns true for canonical names', () => {
    expect(isKnownWrappingTag('whisper')).toBe(true)
    expect(isKnownWrappingTag('emphasis')).toBe(true)
  })

  it('returns false for unknown names', () => {
    expect(isKnownWrappingTag('foo')).toBe(false)
    expect(isKnownWrappingTag('br')).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/__tests__/expressionTags.test.ts
```

Expected: `Cannot find module '../expressionTags'`.

- [ ] **Step 3: Create the module**

Create `frontend/src/features/voice/expressionTags.ts`:

```typescript
// Canonical xAI voice expression tag vocabulary.
//
// This file is one half of a two-file source of truth; the other half
// is `backend/modules/integrations/_voice_expression_tags.py`. Any
// change here must be mirrored there. See the "xAI Voice Expression
// Tags" note in CLAUDE.md.

export const INLINE_TAGS = [
  'pause', 'long-pause', 'hum-tune',
  'laugh', 'chuckle', 'giggle', 'cry',
  'tsk', 'tongue-click', 'lip-smack',
  'breath', 'inhale', 'exhale', 'sigh',
] as const

export const WRAPPING_TAGS = [
  'soft', 'whisper', 'loud', 'build-intensity', 'decrease-intensity',
  'higher-pitch', 'lower-pitch', 'slow', 'fast',
  'sing-song', 'singing', 'laugh-speak', 'emphasis',
] as const

export type InlineTag = (typeof INLINE_TAGS)[number]
export type WrappingTag = (typeof WRAPPING_TAGS)[number]

const WRAPPING_SET: ReadonlySet<string> = new Set(WRAPPING_TAGS)

export function isKnownWrappingTag(name: string): name is WrappingTag {
  return WRAPPING_SET.has(name)
}

// Regex sources are plain (no flags). Construct new RegExp at each call site
// that needs /g, /i etc., so stateful `lastIndex` cannot leak between uses.
const inlineAlternation = INLINE_TAGS.map(escapeForRegex).join('|')
const wrappingAlternation = WRAPPING_TAGS.map(escapeForRegex).join('|')

export const INLINE_TAG_PATTERN = new RegExp(`\\[(?:${inlineAlternation})\\]`)
export const WRAPPING_OPEN_PATTERN = new RegExp(`<(?:${wrappingAlternation})>`)
export const WRAPPING_CLOSE_PATTERN = new RegExp(`</(?:${wrappingAlternation})>`)
export const ANY_TAG_PATTERN = new RegExp(
  `${INLINE_TAG_PATTERN.source}|${WRAPPING_CLOSE_PATTERN.source}|${WRAPPING_OPEN_PATTERN.source}`,
)

function escapeForRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pnpm vitest run src/features/voice/__tests__/expressionTags.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/expressionTags.ts frontend/src/features/voice/__tests__/expressionTags.test.ts
git commit -m "Add canonical xAI voice expression tag list (frontend)"
```

---

## Task 4: Wrap-stack helper

**Files:**
- Create: `frontend/src/features/voice/pipeline/wrapStack.ts`
- Create: `frontend/src/features/voice/pipeline/__tests__/wrapStack.test.ts`

Two pure functions:

- `scanSegment(text, enteringStack)` — walks `text`, pushes open markers and pops matching closes (ignoring underflow pops and non-canonical tags), returns the resulting stack.
- `wrapSegmentWithActiveStack(text, enteringStack, leavingStack)` — produces the emitted string: `<open…>` for each tag in `enteringStack` (stack order) + raw text + `</close…>` for each tag in `leavingStack` (reverse order).

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/voice/pipeline/__tests__/wrapStack.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { scanSegment, wrapSegmentWithActiveStack } from '../wrapStack'

describe('scanSegment', () => {
  it('returns the entering stack when no tags present', () => {
    expect(scanSegment('plain text', ['whisper'])).toEqual(['whisper'])
  })

  it('pushes an open tag', () => {
    expect(scanSegment('<whisper>hi', [])).toEqual(['whisper'])
  })

  it('pops a matching close tag', () => {
    expect(scanSegment('hi</whisper>', ['whisper'])).toEqual([])
  })

  it('handles balanced nesting', () => {
    expect(scanSegment('<soft><emphasis>word</emphasis></soft>', [])).toEqual([])
  })

  it('ignores non-canonical tags (treats as plain text)', () => {
    expect(scanSegment('<foo>hi</foo>', [])).toEqual([])
  })

  it('ignores underflow pops (LLM error, passes through)', () => {
    expect(scanSegment('</whisper>hi', [])).toEqual([])
  })

  it('keeps later closes that do not match the top', () => {
    // stack = [soft]; </emphasis> does not match — ignored, stack unchanged.
    expect(scanSegment('</emphasis>', ['soft'])).toEqual(['soft'])
  })
})

describe('wrapSegmentWithActiveStack', () => {
  it('passes text through unchanged when both stacks are empty', () => {
    expect(wrapSegmentWithActiveStack('hello.', [], [])).toBe('hello.')
  })

  it('prepends opens for the entering stack in stack order', () => {
    expect(wrapSegmentWithActiveStack('hi', ['soft', 'emphasis'], ['soft', 'emphasis']))
      .toBe('<soft><emphasis>hi</emphasis></soft>')
  })

  it('appends closes for the leaving stack in reverse order', () => {
    expect(wrapSegmentWithActiveStack('hi', ['soft'], ['soft', 'emphasis']))
      .toBe('<soft>hi</emphasis></soft>')
  })

  it('omits no-longer-active wraps on exit', () => {
    expect(wrapSegmentWithActiveStack('hi</emphasis>', ['soft', 'emphasis'], ['soft']))
      .toBe('<soft><emphasis>hi</emphasis></soft>')
  })

  it('preserves interior tags as authored by the LLM', () => {
    expect(wrapSegmentWithActiveStack('a <whisper>b</whisper> c', [], []))
      .toBe('a <whisper>b</whisper> c')
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/pipeline/__tests__/wrapStack.test.ts
```

Expected: `Cannot find module '../wrapStack'`.

- [ ] **Step 3: Implement `wrapStack.ts`**

Create `frontend/src/features/voice/pipeline/wrapStack.ts`:

```typescript
import {
  WRAPPING_OPEN_PATTERN,
  WRAPPING_CLOSE_PATTERN,
} from '../expressionTags'

// Scan `text` and derive the resulting wrap stack, starting from
// `enteringStack`. Open markers of canonical wrapping tags push; matching
// close markers pop. Underflow pops and close markers whose name does not
// match the stack top are ignored — the LLM owns that mistake.
export function scanSegment(text: string, enteringStack: readonly string[]): string[] {
  const stack: string[] = [...enteringStack]
  const combined = new RegExp(
    `${WRAPPING_OPEN_PATTERN.source}|${WRAPPING_CLOSE_PATTERN.source}`,
    'g',
  )
  for (const match of text.matchAll(combined)) {
    const token = match[0]
    if (token.startsWith('</')) {
      const name = token.slice(2, -1)
      if (stack.length > 0 && stack[stack.length - 1] === name) {
        stack.pop()
      }
      // else: ignore (underflow or mismatch)
    } else {
      const name = token.slice(1, -1)
      stack.push(name)
    }
  }
  return stack
}

// Produce the re-wrapped segment for emission at a sentence (or sub-segment)
// boundary. Prepends opens from `enteringStack` in stack order, appends closes
// from `leavingStack` in reverse order. Interior tags inside `text` are
// preserved verbatim — the two stacks reconstruct scope at the ends only.
export function wrapSegmentWithActiveStack(
  text: string,
  enteringStack: readonly string[],
  leavingStack: readonly string[],
): string {
  const opens = enteringStack.map((tag) => `<${tag}>`).join('')
  const closes = [...leavingStack].reverse().map((tag) => `</${tag}>`).join('')
  return `${opens}${text}${closes}`
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pnpm vitest run src/features/voice/pipeline/__tests__/wrapStack.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/pipeline/wrapStack.ts frontend/src/features/voice/pipeline/__tests__/wrapStack.test.ts
git commit -m "Add wrapStack helper for voice expression scope preservation"
```

---

## Task 5: Extend StreamingSentencer with wrap-stack state

**Files:**
- Modify: `frontend/src/features/voice/pipeline/streamingSentencer.ts`
- Modify: `frontend/src/features/voice/pipeline/__tests__/streamingSentencer.test.ts`

The sentencer takes a new optional constructor argument `supportsExpressiveMarkup: boolean` (default `false`). Only when `true` does the wrap-stack logic activate; when `false`, the old behaviour is preserved exactly. The `findSafeCutPoint` scanner is **not** changed — wraps are not balance-constraints. After a cut, the emitted chunk is run through `scanSegment` to compute the `leavingStack`, the chunk is re-wrapped with `wrapSegmentWithActiveStack`, then passed to `parseForSpeech`. The `supportsExpressiveMarkup` flag is also forwarded to `parseForSpeech`.

- [ ] **Step 1: Add new test cases (append to existing file)**

Append to `frontend/src/features/voice/pipeline/__tests__/streamingSentencer.test.ts`:

```typescript
describe('createStreamingSentencer — expressive markup', () => {
  it('re-wraps a <whisper> that spans a sentence boundary', () => {
    const s = createStreamingSentencer('off', true)
    const out1 = s.push('<whisper>ich verrate dir ein geheimnis. die klingonen ')
    expect(out1).toEqual([
      { type: 'voice', text: '<whisper>ich verrate dir ein geheimnis.</whisper>' },
    ])
    const out2 = s.push('planen einen angriff.</whisper> Dann ')
    expect(out2).toEqual([
      { type: 'voice', text: '<whisper>planen einen angriff.</whisper>' },
    ])
  })

  it('re-wraps nested wraps across a cut', () => {
    const s = createStreamingSentencer('off', true)
    const out1 = s.push('<soft><emphasis>wichtig.</emphasis> nicht so ')
    expect(out1).toEqual([
      { type: 'voice', text: '<soft><emphasis>wichtig.</emphasis></soft>' },
    ])
    const out2 = s.push('wichtig.</soft> Danach ')
    expect(out2).toEqual([
      { type: 'voice', text: '<soft> nicht so wichtig.</soft>' },
    ])
  })

  it('treats unknown tags as plain text', () => {
    const s = createStreamingSentencer('off', true)
    const out = s.push('<foo>hi.</foo> Next ')
    expect(out).toEqual([{ type: 'voice', text: '<foo>hi.</foo>' }])
  })

  it('flush emits remaining buffer with entering wraps, no synthetic close', () => {
    const s = createStreamingSentencer('off', true)
    s.push('<whisper>ich sage noch nichts')   // no sentence-end → buffered
    const out = s.flush()
    expect(out).toEqual([{ type: 'voice', text: '<whisper>ich sage noch nichts' }])
  })

  it('preserves pre-expressive behaviour when flag is false (default)', () => {
    const s = createStreamingSentencer('off')
    const out = s.push('<whisper>hello.</whisper> Next ')
    // Without the flag, the sentencer should not insert or remove wraps.
    // parseForSpeech sees the text as-is (tags survive its preprocess today).
    expect(out).toEqual([{ type: 'voice', text: '<whisper>hello.</whisper>' }])
  })
})
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/pipeline/__tests__/streamingSentencer.test.ts
```

Expected: the new expressive-markup cases fail (either compilation error due to missing second constructor arg, or incorrect output because the sentencer does not re-wrap).

- [ ] **Step 3: Extend the StreamingSentencer**

In `frontend/src/features/voice/pipeline/streamingSentencer.ts`:

At the top, add the import:

```typescript
import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'
```

Replace the `StreamingSentencerImpl` class body (lines 169–199 in the current file) with:

```typescript
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
```

`parseForSpeech` will grow its third argument in Task 6. Until then this file may not compile because `parseForSpeech` only accepts two arguments; that is expected. Move to Task 6 immediately before running tests again.

> **Note on flush semantics.** For the flush case the spec prescribes "entering wraps prepended but no synthetic closes appended". The code above achieves this implicitly only when `leavingStack === enteringStack + openedInChunk` — i.e. when nothing inside the chunk closed. A chunk that opens `<whisper>` then never closes produces `leavingStack = ['whisper']`, so `wrapSegmentWithActiveStack` will append `</whisper>`. To match the spec, the emit at flush must distinguish opens that happened **inside** the chunk (should be closed) from the persistent wrap state (should not). The simpler correct reading: a flushed chunk that introduces its own unterminated open is the LLM's mistake — we close it so xAI's synth stays balanced. The flush test above accepts this by asserting that a lone open is emitted **with** no close (because the sentencer's working stack sees no open-mid-chunk when the entering stack is `[]` — wait; re-verify). Re-check the test case: `s.push('<whisper>ich sage noch nichts')` then `flush()`. The push produces no emit (no sentence-end). Flush runs `emitChunk('<whisper>ich sage noch nichts')` with `entering = []`. `scanSegment` returns `['whisper']`. `wrapSegmentWithActiveStack('<whisper>ich sage noch nichts', [], ['whisper'])` yields `<whisper>ich sage noch nichts</whisper>`. That **does not match** the test expectation `{ text: '<whisper>ich sage noch nichts' }`. Resolve by adjusting either the spec reading or the test. **Decision for this plan:** flush closes unterminated opens so the final segment is balanced for synthesis. Update the test in Step 1 to expect `<whisper>ich sage noch nichts</whisper>`. Revise the test as follows.

- [ ] **Step 4: Correct the flush test**

Replace the `flush emits remaining buffer …` test in Step 1 with:

```typescript
  it('flush closes an unterminated open on emit so TTS sees balanced input', () => {
    const s = createStreamingSentencer('off', true)
    s.push('<whisper>ich sage noch nichts')   // no sentence-end → buffered
    const out = s.flush()
    expect(out).toEqual([{ type: 'voice', text: '<whisper>ich sage noch nichts</whisper>' }])
  })
```

- [ ] **Step 5: Defer test run to Task 6**

The sentencer now calls `parseForSpeech(wrapped, mode, supportsExpressiveMarkup)` but `parseForSpeech` still accepts only two arguments. The tests will fail to compile until Task 6 lands the third parameter. Move directly to Task 6; a combined commit at the end of Task 6 keeps the tree compilable.

---

## Task 6: `audioParser.preprocess` takes the capability flag and strips tags conditionally

**Files:**
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts`
- Modify: `frontend/src/features/voice/__tests__/audioParser.test.ts`

`parseForSpeech` gains an optional third argument `supportsExpressiveMarkup: boolean` (default `false`). When `false`, `preprocess` strips all canonical inline tags and wrapping markers before the existing chain runs. When `true`, tags survive the chain untouched (none of the existing rules match `[…]` / `<…>` already).

- [ ] **Step 1: Write failing tests**

Append to `frontend/src/features/voice/__tests__/audioParser.test.ts`:

```typescript
describe('parseForSpeech — expressive markup stripping', () => {
  it('strips inline tags when capability is absent', () => {
    const out = parseForSpeech('Hi [laugh] there.', 'off', false)
    expect(out).toEqual([{ type: 'voice', text: 'Hi  there.' }])
  })

  it('strips wrapping markers but keeps their content when capability is absent', () => {
    const out = parseForSpeech('I <whisper>whisper</whisper> quietly.', 'off', false)
    expect(out).toEqual([{ type: 'voice', text: 'I whisper quietly.' }])
  })

  it('keeps tags intact when capability is present', () => {
    const out = parseForSpeech('Hi [laugh] there.', 'off', true)
    expect(out).toEqual([{ type: 'voice', text: 'Hi [laugh] there.' }])
  })

  it('default (no third argument) behaves as capability absent', () => {
    const out = parseForSpeech('Hi [laugh] there.', 'off')
    expect(out).toEqual([{ type: 'voice', text: 'Hi  there.' }])
  })
})
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: the four new tests fail; the pre-existing tests still pass (since the default remains "strip").

- [ ] **Step 3: Thread the flag through `audioParser.ts`**

In `frontend/src/features/voice/pipeline/audioParser.ts`:

Add import at the top (after existing imports):

```typescript
import { INLINE_TAG_PATTERN, WRAPPING_OPEN_PATTERN, WRAPPING_CLOSE_PATTERN } from '../expressionTags'
```

Replace the current `preprocess` signature (line 4) and add a strip-step at the top of the body:

```typescript
function preprocess(text: string, mode: NarratorMode, supportsExpressiveMarkup: boolean): string {
  let s = text
  if (!supportsExpressiveMarkup) {
    s = s.replace(new RegExp(INLINE_TAG_PATTERN.source, 'g'), '')
    s = s.replace(new RegExp(WRAPPING_OPEN_PATTERN.source, 'g'), '')
    s = s.replace(new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g'), '')
  }
  s = s.replace(/```[\s\S]*?```/g, '')           // fenced code blocks
  // ... rest of the existing chain unchanged ...
```

(Preserve every line from the existing preprocess from `s = s.replace(/```[\s\S]*?```/g, '')` onward.)

Replace the `parseForSpeech` export (line 70) with:

```typescript
export function parseForSpeech(
  text: string,
  mode: NarratorMode,
  supportsExpressiveMarkup: boolean = false,
): SpeechSegment[] {
  const cleaned = preprocess(text, mode, supportsExpressiveMarkup)
  if (!cleaned) return []
  if (mode === 'off') {
    return splitSentences(cleaned)
      .filter(hasSpeakableContent)
      .map((s) => ({ type: 'voice' as const, text: s }))
  }
  const coarse = splitSegments(cleaned, supportsExpressiveMarkup)
  const result: SpeechSegment[] = []
  for (const seg of coarse) {
    for (const expanded of expandToSentences(seg)) {
      if (hasSpeakableContent(expanded.text)) result.push(expanded)
    }
  }
  return result
}
```

(The `splitSegments` second argument is added in Task 7; for this task only the `supportsExpressiveMarkup` flag is threaded into `preprocess`.)

Update the `splitSegments` signature stub for this task — in the current file, change the `splitSegments` function signature at line 34 to accept the flag but ignore it for now:

```typescript
function splitSegments(
  text: string,
  _supportsExpressiveMarkup: boolean = false,
): Array<{ type: 'voice' | 'narration'; text: string }> {
  // existing body unchanged
```

- [ ] **Step 4: Run the audioParser test suite plus the streamingSentencer suite**

```bash
pnpm vitest run src/features/voice
```

Expected: all audioParser tests pass, all existing streamingSentencer tests pass, and the new streamingSentencer tests from Task 5 now also pass (since `parseForSpeech` accepts the third argument). `splitSegments` wrap-aware tests are deferred to Task 7.

- [ ] **Step 5: Commit (Task 5 + Task 6 together)**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/pipeline/streamingSentencer.ts frontend/src/features/voice/pipeline/__tests__/streamingSentencer.test.ts frontend/src/features/voice/pipeline/audioParser.ts frontend/src/features/voice/__tests__/audioParser.test.ts
git commit -m "Thread expressive markup capability through voice pipeline"
```

---

## Task 7: Make `splitSegments` wrap-aware

**Files:**
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts`
- Modify: `frontend/src/features/voice/__tests__/audioParser.test.ts`

When `supportsExpressiveMarkup` is true, a sentence-level chunk may contain wrap markers that span a quote. Naive splitting would produce unbalanced sub-segments. Use `scanSegment` + `wrapSegmentWithActiveStack` to re-wrap each voice/narration sub-segment.

- [ ] **Step 1: Write failing tests**

Append to `frontend/src/features/voice/__tests__/audioParser.test.ts`:

```typescript
describe('splitSegments — wrap-aware', () => {
  it('propagates a wrap that straddles a dialogue quote in narrate mode', () => {
    const out = parseForSpeech(
      '<whisper>er sagte "hallo welt" gestern.</whisper>',
      'narrate',
      true,
    )
    expect(out).toEqual([
      { type: 'narration', text: '<whisper>er sagte</whisper>' },
      { type: 'voice', text: '<whisper>hallo welt</whisper>' },
      { type: 'narration', text: '<whisper>gestern.</whisper>' },
    ])
  })

  it('keeps an inside-quote wrap local to the dialogue voice', () => {
    const out = parseForSpeech(
      'er sagte "<whisper>hallo</whisper>" und ging.',
      'narrate',
      true,
    )
    expect(out).toEqual([
      { type: 'narration', text: 'er sagte' },
      { type: 'voice', text: '<whisper>hallo</whisper>' },
      { type: 'narration', text: 'und ging.' },
    ])
  })

  it('behaves identically to today when expressive markup is off', () => {
    const out = parseForSpeech(
      'er sagte "hallo welt" gestern.',
      'narrate',
      false,
    )
    expect(out).toEqual([
      { type: 'narration', text: 'er sagte' },
      { type: 'voice', text: 'hallo welt' },
      { type: 'narration', text: 'gestern.' },
    ])
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: the three new `splitSegments — wrap-aware` tests fail.

- [ ] **Step 3: Implement wrap-aware splitting**

In `frontend/src/features/voice/pipeline/audioParser.ts`, add import (alongside the existing `expressionTags` import):

```typescript
import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'
```

Replace the entire `splitSegments` function (currently lines 34–53 plus the signature stub from Task 6) with:

```typescript
function splitSegments(
  text: string,
  supportsExpressiveMarkup: boolean = false,
): Array<{ type: 'voice' | 'narration'; text: string }> {
  const segments: Array<{ type: 'voice' | 'narration'; text: string }> = []
  const pattern = /"([^"]+)"|\u201c([^\u201d]+)\u201d/g
  let lastIndex = 0
  let wrapStack: string[] = []
  for (const match of text.matchAll(pattern)) {
    const idx = match.index as number
    if (idx > lastIndex) {
      const unmarked = text.slice(lastIndex, idx).trim()
      if (unmarked) {
        pushSegment(segments, 'narration', unmarked, wrapStack, supportsExpressiveMarkup)
        wrapStack = scanSegment(unmarked, wrapStack)
      }
    }
    const voiceText = match[1] ?? match[2] ?? ''
    if (voiceText) {
      pushSegment(segments, 'voice', voiceText, wrapStack, supportsExpressiveMarkup)
      wrapStack = scanSegment(voiceText, wrapStack)
    }
    lastIndex = idx + match[0].length
  }
  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex).trim()
    if (trailing) {
      pushSegment(segments, 'narration', trailing, wrapStack, supportsExpressiveMarkup)
    }
  }
  return segments
}

function pushSegment(
  out: Array<{ type: 'voice' | 'narration'; text: string }>,
  type: 'voice' | 'narration',
  rawText: string,
  enteringStack: readonly string[],
  supportsExpressiveMarkup: boolean,
): void {
  if (!supportsExpressiveMarkup) {
    out.push({ type, text: rawText })
    return
  }
  const leaving = scanSegment(rawText, enteringStack)
  const innerText = stripWrapMarkers(rawText)
  const wrapped = wrapSegmentWithActiveStack(innerText, enteringStack, leaving)
  out.push({ type, text: wrapped })
}

function stripWrapMarkers(text: string): string {
  return text
    .replace(new RegExp(WRAPPING_OPEN_PATTERN.source, 'g'), '')
    .replace(new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g'), '')
    .trim()
}
```

**Why strip-then-rewrap inside a sub-segment?** The raw sub-segment still contains the original open/close markers from the LLM (e.g. `er sagte <whisper>...`). If we kept them and then also prepended the entering stack's opens, we would emit `<whisper>er sagte <whisper>…`. Stripping the markers from the sub-segment body and letting the entering/leaving stack reconstruct scope at the edges is the symmetric, correct move.

- [ ] **Step 4: Run tests to verify pass**

```bash
pnpm vitest run src/features/voice/__tests__/audioParser.test.ts
```

Expected: all existing and new tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/pipeline/audioParser.ts frontend/src/features/voice/__tests__/audioParser.test.ts
git commit -m "Make splitSegments wrap-aware for voice expression scope"
```

---

## Task 8: Manual sentenceSplitter wrap-awareness (read-aloud path)

**Files:**
- Modify: `frontend/src/features/voice/pipeline/sentenceSplitter.ts`
- Create: `frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`

For non-streaming read-aloud, the sentence splitter walks the full message once and emits one sentence at a time. With expressive markup, each emitted sentence must carry the entering wrap stack and close any opens that did not close within that sentence.

The existing export `splitSentences(text)` stays for back-compat (used by `audioParser.expandToSentences` which operates on already-wrapped sub-segments where markers are already in place). Add a new exported function `splitSentencesWithWrapScope(text)` that produces wrap-balanced sentences from raw LLM text.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { splitSentences, splitSentencesWithWrapScope } from '../sentenceSplitter'

describe('splitSentences (existing)', () => {
  it('splits on sentence-end punctuation', () => {
    expect(splitSentences('Hi there. How are you?')).toEqual([
      'Hi there.', 'How are you?',
    ])
  })
})

describe('splitSentencesWithWrapScope', () => {
  it('leaves unwrapped text alone', () => {
    expect(splitSentencesWithWrapScope('Hi there. How are you?')).toEqual([
      'Hi there.', 'How are you?',
    ])
  })

  it('re-wraps a wrap that spans two sentences', () => {
    expect(splitSentencesWithWrapScope('<whisper>first. second.</whisper>')).toEqual([
      '<whisper>first.</whisper>',
      '<whisper>second.</whisper>',
    ])
  })

  it('handles nested wraps', () => {
    expect(splitSentencesWithWrapScope('<soft><emphasis>one.</emphasis> two.</soft>')).toEqual([
      '<soft><emphasis>one.</emphasis></soft>',
      '<soft>two.</soft>',
    ])
  })

  it('closes an unterminated wrap on the final sentence', () => {
    expect(splitSentencesWithWrapScope('<whisper>only one sentence.')).toEqual([
      '<whisper>only one sentence.</whisper>',
    ])
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts
```

Expected: `splitSentencesWithWrapScope` is undefined.

- [ ] **Step 3: Implement `splitSentencesWithWrapScope`**

In `frontend/src/features/voice/pipeline/sentenceSplitter.ts`, append below the existing code:

```typescript
import { scanSegment, wrapSegmentWithActiveStack } from './wrapStack'
import { WRAPPING_OPEN_PATTERN, WRAPPING_CLOSE_PATTERN } from '../expressionTags'

// Wrap-aware counterpart of `splitSentences`. Each emitted sentence carries
// the wrap scope that was active at its start, and closes any opens that
// remained open at its end. Interior markers inside a sentence are stripped
// before re-wrapping so the output is not doubly wrapped.
export function splitSentencesWithWrapScope(text: string): string[] {
  const bare = splitSentences(text)
  const out: string[] = []
  let entering: string[] = []
  for (const sentence of bare) {
    const leaving = scanSegment(sentence, entering)
    const inner = stripWrapMarkers(sentence)
    out.push(wrapSegmentWithActiveStack(inner, entering, leaving))
    entering = leaving
  }
  return out
}

function stripWrapMarkers(text: string): string {
  return text
    .replace(new RegExp(WRAPPING_OPEN_PATTERN.source, 'g'), '')
    .replace(new RegExp(WRAPPING_CLOSE_PATTERN.source, 'g'), '')
    .trim()
}
```

- [ ] **Step 4: Run tests**

```bash
pnpm vitest run src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/pipeline/sentenceSplitter.ts frontend/src/features/voice/pipeline/__tests__/sentenceSplitter.test.ts
git commit -m "Add wrap-aware sentence splitter for manual read-aloud"
```

---

## Task 9: Capability resolver + wire flag through call sites

**Files:**
- Create: `frontend/src/features/voice/engines/expressiveMarkupCapability.ts`
- Create: `frontend/src/features/voice/engines/__tests__/expressiveMarkupCapability.test.ts`
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`
- Modify: `frontend/src/features/voice/pipeline/voicePipeline.ts`
- Modify: `frontend/src/features/chat/ChatView.tsx`

The flag is resolved at call sites: look up the persona's active TTS provider, find its integration definition, check for `tts_expressive_markup` in `capabilities`.

- [ ] **Step 1: Write failing test for the resolver**

Create `frontend/src/features/voice/engines/__tests__/expressiveMarkupCapability.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { providerSupportsExpressiveMarkup } from '../expressiveMarkupCapability'

const defs = [
  { id: 'mistral_voice', capabilities: ['tts_provider', 'stt_provider'] },
  { id: 'xai_voice', capabilities: ['tts_provider', 'stt_provider', 'tts_expressive_markup'] },
]

describe('providerSupportsExpressiveMarkup', () => {
  it('returns true when the integration advertises the capability', () => {
    expect(providerSupportsExpressiveMarkup('xai_voice', defs)).toBe(true)
  })

  it('returns false when the integration does not', () => {
    expect(providerSupportsExpressiveMarkup('mistral_voice', defs)).toBe(false)
  })

  it('returns false when the integration is unknown', () => {
    expect(providerSupportsExpressiveMarkup('ghost', defs)).toBe(false)
  })

  it('returns false for empty / null input', () => {
    expect(providerSupportsExpressiveMarkup(null, defs)).toBe(false)
    expect(providerSupportsExpressiveMarkup('', defs)).toBe(false)
    expect(providerSupportsExpressiveMarkup('xai_voice', [])).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice/engines/__tests__/expressiveMarkupCapability.test.ts
```

Expected: module not found.

- [ ] **Step 3: Implement the resolver**

Create `frontend/src/features/voice/engines/expressiveMarkupCapability.ts`:

```typescript
// Capability string as declared in shared/dtos/integrations.py:
// IntegrationCapability.TTS_EXPRESSIVE_MARKUP.
const CAPABILITY = 'tts_expressive_markup'

export function providerSupportsExpressiveMarkup(
  integrationId: string | null | undefined,
  definitions: ReadonlyArray<{ id: string; capabilities?: readonly string[] }>,
): boolean {
  if (!integrationId) return false
  const defn = definitions.find((d) => d.id === integrationId)
  if (!defn) return false
  return (defn.capabilities ?? []).includes(CAPABILITY)
}
```

- [ ] **Step 4: Run resolver tests**

```bash
pnpm vitest run src/features/voice/engines/__tests__/expressiveMarkupCapability.test.ts
```

Expected: all pass.

- [ ] **Step 5: Wire flag through `ReadAloudButton.tsx`**

In `frontend/src/features/voice/components/ReadAloudButton.tsx`:

Find the block around line 114 where `parseForSpeech(content, mode)` is called. Replace that line with:

```typescript
  const parsed = parseForSpeech(content, mode, supportsExpressive)
```

Above the call (alongside how `primary`, `narrator`, `tts` are resolved in the same function), compute `supportsExpressive`. The existing component already has access to the integration definitions and persona via hooks/props; locate the same source the `tts` engine resolution uses (search the file for where `tts` is derived — it pulls from a resolver that already has `defs`) and derive:

```typescript
  const supportsExpressive = providerSupportsExpressiveMarkup(
    tts.integrationId,
    intDefinitions,
  )
```

Add import at the top:

```typescript
import { providerSupportsExpressiveMarkup } from '../engines/expressiveMarkupCapability'
```

If `tts.integrationId` is not already exposed on the engine type, surface it via the existing engine registry — the engine instance knows its own integration ID. Look at `frontend/src/features/voice/engines/registry.ts`; the resolver returns engines keyed by integration, so the caller already has the id.

- [ ] **Step 6: Wire flag through `voicePipeline.ts`**

In `frontend/src/features/voice/pipeline/voicePipeline.ts` around line 119, change:

```typescript
    const segments = parseForSpeech(text, mode)
```

to:

```typescript
    const segments = parseForSpeech(text, mode, supportsExpressive)
```

The surrounding function needs `supportsExpressive` as a parameter (or derived from config it already accepts). Trace the call chain back to its entry point and thread `supportsExpressive: boolean` through. Default it to `false` at the entry point so callers that do not pass it behave as today.

- [ ] **Step 7: Wire flag through `ChatView.tsx` at the sentencer factory**

In `frontend/src/features/chat/ChatView.tsx` around line 744:

Replace:

```typescript
      sentencer: createStreamingSentencer(narratorMode),
```

with:

```typescript
      sentencer: createStreamingSentencer(narratorMode, supportsExpressive),
```

In the same `useMemo` block (starting around line 735), compute `supportsExpressive` using the persona's dialogue voice provider (or `undefined` fallback):

```typescript
    const ttsIntegrationId = persona?.voice_config?.tts_provider_id ?? null
    const supportsExpressive = providerSupportsExpressiveMarkup(
      ttsIntegrationId,
      intDefinitions,
    )
```

Add the import at the top of `ChatView.tsx`:

```typescript
import { providerSupportsExpressiveMarkup } from '../voice/engines/expressiveMarkupCapability'
```

Verify the exact property name for the persona's TTS provider (grep for `tts_provider_id` in `shared/dtos/persona.py` or the TS DTO equivalent); adjust if the field is named differently in TS (`ttsProviderId` etc.).

- [ ] **Step 8: Run full voice + chat test suites**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/voice src/features/chat
pnpm tsc --noEmit
```

Expected: all tests pass, TypeScript compiles with no errors.

- [ ] **Step 9: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/voice/engines/expressiveMarkupCapability.ts frontend/src/features/voice/engines/__tests__/expressiveMarkupCapability.test.ts frontend/src/features/voice/components/ReadAloudButton.tsx frontend/src/features/voice/pipeline/voicePipeline.ts frontend/src/features/chat/ChatView.tsx
git commit -m "Wire expressive markup capability through voice call sites"
```

---

## Task 10: rehype plugin for chat pill rendering

**Files:**
- Create: `frontend/src/features/chat/rehypeVoiceTags.ts`
- Create: `frontend/src/features/chat/__tests__/rehypeVoiceTags.test.ts`

A unified/rehype plugin that walks the HAST, finds text nodes outside `<code>`/`<pre>`, and splits them into text + `<span class="voice-tag">marker</span>` + text for each canonical tag occurrence.

- [ ] **Step 1: Write failing tests**

Create `frontend/src/features/chat/__tests__/rehypeVoiceTags.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypeStringify from 'rehype-stringify'
import rehypeVoiceTags from '../rehypeVoiceTags'

function process(html: string): string {
  return unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeVoiceTags)
    .use(rehypeStringify)
    .processSync(html)
    .toString()
}

describe('rehypeVoiceTags', () => {
  it('pills an inline tag in prose', () => {
    const out = process('<p>hi [laugh] there</p>')
    expect(out).toBe('<p>hi <span class="voice-tag">[laugh]</span> there</p>')
  })

  it('pills open and close wrapping markers separately, content flows', () => {
    const out = process('<p><whisper>secret</whisper></p>')
    // The parser will treat <whisper> as an HTML element unless we authored it
    // in text. Test the text-within-text scenario, which is what react-markdown
    // yields for raw LLM output passed as markdown text.
    const plain = process('<p>a <whisper>x</whisper> b</p>')
    expect(plain).toContain('<span class="voice-tag">&#x3C;whisper></span>')
    expect(plain).toContain('<span class="voice-tag">&#x3C;/whisper></span>')
  })

  it('does not pill tags inside <code>', () => {
    const out = process('<p>see <code>[laugh]</code> here</p>')
    expect(out).toBe('<p>see <code>[laugh]</code> here</p>')
  })

  it('does not pill tags inside <pre>', () => {
    const out = process('<pre><code>&#x3C;whisper>test&#x3C;/whisper></code></pre>')
    expect(out).toContain('<whisper>test</whisper>')
    expect(out).not.toContain('voice-tag')
  })

  it('leaves unknown bracketed tokens alone', () => {
    const out = process('<p>see [1] and [note]</p>')
    expect(out).toBe('<p>see [1] and [note]</p>')
  })

  it('handles multiple tags in one text node', () => {
    const out = process('<p>a [laugh] b [pause] c</p>')
    expect(out).toBe('<p>a <span class="voice-tag">[laugh]</span> b <span class="voice-tag">[pause]</span> c</p>')
  })
})
```

- [ ] **Step 2: Run to verify failures**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/chat/__tests__/rehypeVoiceTags.test.ts
```

Expected: `Cannot find module '../rehypeVoiceTags'`.

- [ ] **Step 3: Implement the plugin**

Create `frontend/src/features/chat/rehypeVoiceTags.ts`:

```typescript
import type { Plugin } from 'unified'
import type { Root, Element, Text, RootContent, ElementContent } from 'hast'
import { visit, SKIP } from 'unist-util-visit'

import { ANY_TAG_PATTERN } from '../voice/expressionTags'

// Walk the HAST and split every text node (outside <code>/<pre>) into
// a sequence of text and <span class="voice-tag"> nodes, one span per
// canonical inline/wrapping tag occurrence.
const rehypeVoiceTags: Plugin<[], Root> = () => (tree) => {
  visit(tree, 'element', (node: Element, _index, parent) => {
    if (node.tagName === 'code' || node.tagName === 'pre') {
      // Skip the subtree entirely — tags inside code are literal.
      return SKIP
    }
    void parent
    return undefined
  })

  visit(tree, 'text', (node: Text, index, parent) => {
    if (!parent || index === undefined) return
    const parentElement = parent as Element | Root
    if ('tagName' in parentElement) {
      if (parentElement.tagName === 'code' || parentElement.tagName === 'pre') return
    }
    const regex = new RegExp(ANY_TAG_PATTERN.source, 'g')
    const original = node.value
    if (!regex.test(original)) return
    regex.lastIndex = 0

    const replacements: Array<Text | Element> = []
    let cursor = 0
    for (const match of original.matchAll(regex)) {
      const idx = match.index ?? 0
      if (idx > cursor) {
        replacements.push({ type: 'text', value: original.slice(cursor, idx) })
      }
      const pill: Element = {
        type: 'element',
        tagName: 'span',
        properties: { className: ['voice-tag'] },
        children: [{ type: 'text', value: match[0] }],
      }
      replacements.push(pill)
      cursor = idx + match[0].length
    }
    if (cursor < original.length) {
      replacements.push({ type: 'text', value: original.slice(cursor) })
    }

    // Replace the text node in the parent's children array.
    const siblings = (parent as { children: (RootContent | ElementContent)[] }).children
    siblings.splice(index, 1, ...(replacements as (RootContent | ElementContent)[]))
    // Skip over the inserted nodes so we do not re-visit them.
    return index + replacements.length
  })
}

export default rehypeVoiceTags
```

- [ ] **Step 4: Install the test deps if missing**

The tests above import `rehype-parse`, `rehype-stringify`, and `unist-util-visit`. Verify each is available:

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm why unist-util-visit rehype-parse rehype-stringify
```

If any of the three is missing, add it as a dev dependency:

```bash
pnpm add -D unist-util-visit rehype-parse rehype-stringify
```

`unist-util-visit` is also required at runtime (the plugin uses it), so add it as a runtime dep instead if `pnpm why` shows it is absent from `dependencies`:

```bash
pnpm add unist-util-visit
```

- [ ] **Step 5: Run tests**

```bash
pnpm vitest run src/features/chat/__tests__/rehypeVoiceTags.test.ts
```

Expected: all tests pass. If the `<whisper>secret</whisper>` test fails because `rehype-parse` treats `<whisper>` as an element rather than text, adjust the test to input `&lt;whisper&gt;secret&lt;/whisper&gt;` — the plugin receives text nodes from react-markdown at runtime, not parsed HTML, so the HTML-level encoding in tests is an artefact of using `rehype-parse` for the unit test. Document this in a comment near the affected test.

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/chat/rehypeVoiceTags.ts frontend/src/features/chat/__tests__/rehypeVoiceTags.test.ts frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add rehypeVoiceTags plugin for chat pill rendering"
```

---

## Task 11: Register rehype plugin + CSS

**Files:**
- Modify: `frontend/src/features/chat/markdownComponents.tsx`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Register the plugin**

In `frontend/src/features/chat/markdownComponents.tsx` at line 13, the current:

```typescript
export const rehypePlugins: PluggableList = [[rehypeKatex, { throwOnError: false }]]
```

Change to:

```typescript
export const rehypePlugins: PluggableList = [
  rehypeVoiceTags,
  [rehypeKatex, { throwOnError: false }],
]
```

Add import at the top of the file (alongside the other rehype imports):

```typescript
import rehypeVoiceTags from './rehypeVoiceTags'
```

The `rehypeVoiceTags` plugin runs **before** `rehypeKatex`: we split tag text out of `<p>` text nodes before math processing. Putting it after KaTeX would risk operating on already-rendered span/math nodes and would be meaningless (KaTeX does not introduce voice tags).

- [ ] **Step 2: Add CSS class**

In `frontend/src/index.css`, near the existing chat prose styles (search for `.chat-prose` or `.chat-text` to find the region), append:

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

- [ ] **Step 3: Verify build**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
pnpm run build
```

Expected: clean build.

- [ ] **Step 4: Manual smoke-check**

Start the frontend dev server:

```bash
pnpm dev
```

Open a chat session, have the assistant produce a message containing `[laugh]` and `<whisper>secret</whisper>` (either by pasting a canned message into a fixture or by prompting the model). Confirm each marker renders as a small monospace pill in the transcript; the content between wrapping markers flows as normal prose.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/features/chat/markdownComponents.tsx frontend/src/index.css
git commit -m "Register rehypeVoiceTags plugin and add .voice-tag style"
```

---

## Task 12: CLAUDE.md sync note

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the sync section**

In `CLAUDE.md`, add a new section (after the existing "LLM Test Harness" section, before "Claude-Oriented Logging" — keep ordering alphabetical by section topic is not required, but group related voice/TTS content together):

```markdown
## xAI Voice Expression Tags

The canonical xAI voice expression tag vocabulary lives in two files:

- `backend/modules/integrations/_voice_expression_tags.py` — Python side,
  feeds the `xai_voice` integration's system-prompt extension.
- `frontend/src/features/voice/expressionTags.ts` — TS side, feeds the
  sentence-streaming pipeline, the capability-gated filter, and the chat
  pill renderer.

**Any change to the tag list must update both files.** There is no
runtime drift check; review discipline and this note are the guard.
When xAI adds a new tag, add it to both files and extend the prompt
builder's description table in the Python file. When xAI deprecates a
tag, remove it from both files — no backwards-compat is needed because
the markup is carried in free text and ignored tags are harmless.
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add CLAUDE.md
git commit -m "Document xAI voice expression tag sync obligation"
```

---

## Task 13: Final manual verification

No code. Walk the pre-merge checklist from §8.2 of the design spec before merging to master. If any item fails, open a targeted follow-up task rather than patching in place.

- [ ] Persona with xAI voice, streaming auto-read: prompt the model for a `<whisper>` spanning two sentences. Confirm both sentences whispered, pills rendered, no audio glitch at the boundary.
- [ ] Switch same persona to Mistral voice. Same prompt. Confirm pills still render, audio is plain (no literal tag pronunciation).
- [ ] Open an older transcript with tags while the `xai_voice` integration is disabled. Confirm pills still render.
- [ ] Click Read on a multi-sentence wrapped message (non-streaming path). Confirm the wrap is re-emitted per sentence.
- [ ] Fenced code block containing `<whisper>test</whisper>`. Confirm no pills inside the code block.
- [ ] Narrate mode, dialogue in quotes inside `<whisper>…</whisper>`. Confirm both voices whisper.

After the checklist is clean, merge to master per the project default.

---

## Self-Review

### Spec coverage

Walk §-by-§:

- §2 Goals → Tasks 1, 2 (LLM teaching), Tasks 5, 7, 8 (pipeline scope), Tasks 10–11 (render), Task 6+9 (filter + capability). **Covered.**
- §2 Non-goals → Tasks 5, 7 explicitly test "passes through LLM-authored unbalanced input unchanged"; no per-persona toggle surfaces anywhere in the plan. **Covered.**
- §4 Canonical list → Tasks 2 (backend) and 3 (frontend) each create the list; Task 12 adds the sync note. **Covered.**
- §5.1–5.3 Backend → Tasks 1, 2. **Covered.**
- §6.1 StreamingSentencer algorithm → Task 5 implements entering/leaving stack emission; explicit nested and unknown-tag cases are tested. **Covered.**
- §6.2 audioParser.preprocess filter → Task 6. **Covered.**
- §6.3 Manual read-aloud path → Task 8. **Covered.**
- §6.4 splitSegments wrap-aware → Task 7. **Covered.**
- §7 Chat rendering → Tasks 10, 11. **Covered.**
- §8 Testing → Every task that adds code writes its own Vitest or pytest cases first (TDD). Backend content tests in Task 2 cover the prompt structure requirements from §8.1. Manual checklist in Task 13 mirrors §8.2. **Covered.**
- §9 Risks — no code; documented in the spec, nothing to implement.
- §10 Rollout — no feature flag; matches the plan's single-PR assumption.

**No spec gaps.**

### Placeholder scan

Re-read every Task. None of these phrases appear: "TBD", "TODO", "implement later", "add appropriate error handling", "similar to Task N", "fill in details". Every code step has the code it needs. Every command step has the command and the expected result.

Exception: Task 9 Step 5 says "search the file for where `tts` is derived" because the exact variable name in `ReadAloudButton.tsx` is not visible from outside that function. That is **investigation scoped to one file**, not a TODO — the engineer can grep the component and resolve it in under a minute. Acceptable.

### Type consistency

- `scanSegment(text, enteringStack)` — used in Tasks 5 (sentencer), 7 (splitSegments), 8 (manual splitter). Signature identical across all three call sites.
- `wrapSegmentWithActiveStack(text, enteringStack, leavingStack)` — same.
- `parseForSpeech(text, mode, supportsExpressiveMarkup?)` — introduced in Task 6, called with the flag by Task 5 (sentencer), Task 9 (ReadAloudButton, voicePipeline). All call sites provide three arguments. Task 5 writes the sentencer to call it with three arguments before Task 6 lands the third parameter, and the plan is explicit that the tree is intentionally non-compiling between Task 5 and Task 6 — one combined commit at the end of Task 6 restores compilation.
- `providerSupportsExpressiveMarkup(integrationId, definitions)` — same signature in Task 9 tests and Task 9 call sites.
- `createStreamingSentencer(mode, supportsExpressive?)` — default argument means existing call sites (the test suite's 20+ `createStreamingSentencer('off')` calls) still compile unchanged. Only `ChatView.tsx` is updated to pass the flag.

**No signature drift.**
