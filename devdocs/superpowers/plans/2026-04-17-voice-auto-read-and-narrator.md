# Voice Auto-Read Indicator & Narrator Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three usability bugs in the voice integration (missing auto-read indicator, missing abort gesture, stale cache after voice change) and ship the narrator mode feature with a separately selectable narrator voice.

**Architecture:**
- Frontend: centralise the read-aloud state into a single global tuple, extract the cache key, add the narrator-voice dropdown + mode dropdown + preview buttons to `PersonaVoiceConfig`.
- Backend: swap `voice_config.roleplay_mode: bool` for `voice_config.narrator_mode: Literal['off','play','narrate']` with a pydantic `model_validator(mode='before')` translating legacy documents on read. Add a `narrator_voice_id` entry to the `mistral_voice` integration's `persona_config_fields`.
- Parser: switch from a boolean flag to a three-mode enum and add the inverted `narrate` branch.

**Tech Stack:** React 19 + Vite + TypeScript + vitest (frontend); Python 3.12 + FastAPI + Pydantic v2 + pytest (backend).

Spec: `devdocs/superpowers/specs/2026-04-17-voice-auto-read-and-narrator-design.md`.

---

## File Structure

**Created:**
- `frontend/src/features/voice/pipeline/readAloudCacheKey.ts` — single-responsibility helper so the key format is testable in isolation.
- `frontend/src/features/voice/pipeline/__tests__/readAloudCacheKey.test.ts` — unit tests for the helper.
- `tests/modules/persona/test_voice_config_legacy.py` — pytest for the legacy-`roleplay_mode` translator.

**Modified:**
- `frontend/src/features/voice/pipeline/audioParser.ts` — boolean → `NarratorMode` enum + new `narrate` branch.
- `frontend/src/features/voice/__tests__/audioParser.test.ts` — updated cases for all three modes.
- `frontend/src/features/voice/components/ReadAloudButton.tsx` — centralise state, narrator voice resolution, cache-key helper usage.
- `frontend/src/features/voice/components/PersonaVoiceConfig.tsx` — mode dropdown, narrator voice dropdown, preview buttons.
- `frontend/src/features/voice/types.ts` — export `NarratorMode` type.
- `frontend/src/features/integrations/plugins/mistral_voice/index.ts` — handle `narrator_voice_id` in `getPersonaConfigOptions`.
- `frontend/src/core/types/persona.ts` — `voice_config.roleplay_mode` → `narrator_mode`.
- `frontend/src/features/chat/ChatView.tsx` — resolve `narrator_mode` instead of the boolean, pass through to `triggerReadAloud`.
- `shared/dtos/persona.py` — `VoiceConfigDto.narrator_mode` + `model_validator`.
- `backend/modules/integrations/_registry.py` — add `narrator_voice_id` field under `mistral_voice`.
- `tests/modules/integrations/test_registry_capabilities.py` — assert `narrator_voice_id` exists.

---

## Task 1: Parser — `NarratorMode` enum + `narrate` branch

**Files:**
- Modify: `frontend/src/features/voice/pipeline/audioParser.ts`
- Modify: `frontend/src/features/voice/__tests__/audioParser.test.ts`
- Modify: `frontend/src/features/voice/types.ts`

- [ ] **Step 1: Add `NarratorMode` type to `types.ts`**

Append to `frontend/src/features/voice/types.ts` (at end of file):

```ts
export type NarratorMode = 'off' | 'play' | 'narrate'
```

- [ ] **Step 2: Rewrite parser tests for the three modes**

Replace the contents of `frontend/src/features/voice/__tests__/audioParser.test.ts` with:

```ts
import { describe, expect, it } from 'vitest'
import { parseForSpeech } from '../pipeline/audioParser'

describe('parseForSpeech', () => {
  describe("mode 'off'", () => {
    it('treats everything as a single voice segment', () => {
      expect(parseForSpeech('Hello, how are you?', 'off')).toEqual([{ type: 'voice', text: 'Hello, how are you?' }])
    })
    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', 'off')).toEqual([])
    })
  })

  describe("mode 'play' (dialogue spoken, narration narrated)", () => {
    it('splits quoted dialogue from narration', () => {
      const result = parseForSpeech('*walks over* "Hello there!" *waves*', 'play')
      expect(result).toEqual([
        { type: 'narration', text: 'walks over' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'narration', text: 'waves' },
      ])
    })
    it('treats unmarked text as narration', () => {
      expect(parseForSpeech('She looked away quietly.', 'play')).toEqual([
        { type: 'narration', text: 'She looked away quietly.' },
      ])
    })
    it('handles consecutive dialogue segments', () => {
      expect(parseForSpeech('"Hi!" "How are you?"', 'play')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
      ])
    })
  })

  describe("mode 'narrate' (narration narrated, only dialogue spoken)", () => {
    it('swaps the roles: prose and actions become narration, quotes become voice', () => {
      const result = parseForSpeech('*walks over* "Hello there!" *waves*', 'narrate')
      expect(result).toEqual([
        { type: 'narration', text: '*walks over*' },
        { type: 'voice', text: 'Hello there!' },
        { type: 'narration', text: '*waves*' },
      ])
    })
    it('treats unmarked text as narration', () => {
      expect(parseForSpeech('She looked away quietly.', 'narrate')).toEqual([
        { type: 'narration', text: 'She looked away quietly.' },
      ])
    })
    it('keeps consecutive dialogue segments as voice', () => {
      expect(parseForSpeech('"Hi!" "How are you?"', 'narrate')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'voice', text: 'How are you?' },
      ])
    })
    it('emits narration between quotes', () => {
      expect(parseForSpeech('"Hi!" he said. "Bye!"', 'narrate')).toEqual([
        { type: 'voice', text: 'Hi!' },
        { type: 'narration', text: 'he said.' },
        { type: 'voice', text: 'Bye!' },
      ])
    })
  })

  describe('pre-processing (mode-agnostic)', () => {
    it('strips code blocks', () => {
      expect(parseForSpeech('Here is some code:\n```js\nconsole.log("hi")\n```\nDone.', 'off')).toEqual([
        { type: 'voice', text: 'Here is some code:\nDone.' },
      ])
    })
    it('strips inline code', () => {
      expect(parseForSpeech('Use the `console.log` function.', 'off')).toEqual([
        { type: 'voice', text: 'Use the  function.' },
      ])
    })
    it('strips OOC markers', () => {
      expect(parseForSpeech('"Hello!" (( this is OOC )) *smiles*', 'play')).toEqual([
        { type: 'voice', text: 'Hello!' },
        { type: 'narration', text: 'smiles' },
      ])
    })
    it('strips markdown bold and italic', () => {
      expect(parseForSpeech('This is **bold** and __also bold__.', 'off')).toEqual([
        { type: 'voice', text: 'This is bold and also bold.' },
      ])
    })
    it('strips markdown headings', () => {
      expect(parseForSpeech('## Section Title\nSome text.', 'off')).toEqual([
        { type: 'voice', text: 'Section Title\nSome text.' },
      ])
    })
    it('strips markdown links', () => {
      expect(parseForSpeech('Click [here](https://example.com) now.', 'off')).toEqual([
        { type: 'voice', text: 'Click here now.' },
      ])
    })
    it('strips URLs', () => {
      expect(parseForSpeech('Visit https://example.com for details.', 'off')).toEqual([
        { type: 'voice', text: 'Visit  for details.' },
      ])
    })
    it('strips list markers', () => {
      expect(parseForSpeech('- First item\n- Second item\n1. Numbered', 'off')).toEqual([
        { type: 'voice', text: 'First item\nSecond item\nNumbered' },
      ])
    })
    it('returns empty array for empty input', () => {
      expect(parseForSpeech('', 'off')).toEqual([])
    })
    it('returns empty array for code-only input', () => {
      expect(parseForSpeech('```js\ncode\n```', 'off')).toEqual([])
    })
  })
})
```

- [ ] **Step 3: Run tests — expect failures**

Run: `cd frontend && pnpm vitest run src/features/voice/__tests__/audioParser.test.ts`
Expected: FAIL — TypeScript compile error on `parseForSpeech(..., 'off')` because the current signature takes `boolean`; also all `'narrate'` cases.

- [ ] **Step 4: Rewrite the parser**

Replace the contents of `frontend/src/features/voice/pipeline/audioParser.ts` with:

```ts
import type { NarratorMode, SpeechSegment } from '../types'

function preprocess(text: string): string {
  let s = text
  s = s.replace(/```[\s\S]*?```/g, '')           // fenced code blocks
  s = s.replace(/`[^`]+`/g, '')                   // inline code
  s = s.replace(/\(\([\s\S]*?\)\)/g, '')          // OOC markers
  s = s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')   // markdown links
  s = s.replace(/https?:\/\/\S+/g, '')            // standalone URLs
  s = s.replace(/^#{1,6}\s+/gm, '')               // headings
  s = s.replace(/\*\*(.+?)\*\*/g, '$1')           // bold
  s = s.replace(/__(.+?)__/g, '$1')               // underline bold
  s = s.replace(/^[-*+]\s+/gm, '')                // unordered list markers
  s = s.replace(/^\d+\.\s+/gm, '')                // ordered list markers
  s = s.replace(/^>\s?/gm, '')                    // blockquotes
  s = s.replace(/\n{2,}/g, '\n')                  // collapse blank lines
  return s.trim()
}

// In 'play' mode: "..." → voice, *...* → narration, else → narration.
// In 'narrate' mode: "..." → voice, everything else (including *...*) → narration.
function splitSegments(text: string, mode: 'play' | 'narrate'): SpeechSegment[] {
  const segments: SpeechSegment[] = []
  const pattern = mode === 'play'
    ? /"([^"]+)"|\u201c([^\u201d]+)\u201d|\*([^*]+)\*/g
    : /"([^"]+)"|\u201c([^\u201d]+)\u201d/g
  let lastIndex = 0
  for (const match of text.matchAll(pattern)) {
    const idx = match.index as number
    if (idx > lastIndex) {
      const unmarked = text.slice(lastIndex, idx).trim()
      if (unmarked) segments.push({ type: 'narration', text: unmarked })
    }
    if (match[1] !== undefined) segments.push({ type: 'voice', text: match[1] })
    else if (match[2] !== undefined) segments.push({ type: 'voice', text: match[2] })
    else if (match[3] !== undefined) segments.push({ type: 'narration', text: match[3] })
    lastIndex = idx + match[0].length
  }
  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex).trim()
    if (trailing) segments.push({ type: 'narration', text: trailing })
  }
  return segments
}

export function parseForSpeech(text: string, mode: NarratorMode): SpeechSegment[] {
  const cleaned = preprocess(text)
  if (!cleaned) return []
  if (mode === 'off') return [{ type: 'voice', text: cleaned }]
  return splitSegments(cleaned, mode)
}
```

Note: in `narrate` mode the `*...*` markers stay verbatim inside the narration segments (they read fine through TTS and match the test expectation `text: '*walks over*'`).

- [ ] **Step 5: Run tests — expect all pass**

Run: `cd frontend && pnpm vitest run src/features/voice/__tests__/audioParser.test.ts`
Expected: PASS.

- [ ] **Step 6: Typecheck to surface downstream callers**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: type errors in `ReadAloudButton.tsx` and `ChatView.tsx` where the old boolean signature is still used. These are fixed in later tasks — note them and move on.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice/types.ts frontend/src/features/voice/pipeline/audioParser.ts frontend/src/features/voice/__tests__/audioParser.test.ts
git commit -m "Switch parseForSpeech to NarratorMode enum and add narrate branch"
```

---

## Task 2: Cache-key helper

**Files:**
- Create: `frontend/src/features/voice/pipeline/readAloudCacheKey.ts`
- Create: `frontend/src/features/voice/pipeline/__tests__/readAloudCacheKey.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/voice/pipeline/__tests__/readAloudCacheKey.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { readAloudCacheKey } from '../readAloudCacheKey'

describe('readAloudCacheKey', () => {
  it('joins all four components with colons', () => {
    expect(readAloudCacheKey('msg-1', 'voice-a', 'narr-b', 'play')).toBe('msg-1:voice-a:narr-b:play')
  })
  it('renders null narrator voice as a dash', () => {
    expect(readAloudCacheKey('msg-1', 'voice-a', null, 'off')).toBe('msg-1:voice-a:-:off')
  })
  it('differs when the primary voice changes', () => {
    expect(readAloudCacheKey('m', 'v1', null, 'off')).not.toBe(readAloudCacheKey('m', 'v2', null, 'off'))
  })
  it('differs when the mode changes', () => {
    expect(readAloudCacheKey('m', 'v', null, 'off')).not.toBe(readAloudCacheKey('m', 'v', null, 'play'))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/voice/pipeline/__tests__/readAloudCacheKey.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/features/voice/pipeline/readAloudCacheKey.ts`:

```ts
import type { NarratorMode } from '../types'

export function readAloudCacheKey(
  messageId: string,
  primaryVoiceId: string,
  narratorVoiceId: string | null,
  mode: NarratorMode,
): string {
  return `${messageId}:${primaryVoiceId}:${narratorVoiceId ?? '-'}:${mode}`
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/voice/pipeline/__tests__/readAloudCacheKey.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/pipeline/readAloudCacheKey.ts frontend/src/features/voice/pipeline/__tests__/readAloudCacheKey.test.ts
git commit -m "Add readAloudCacheKey helper with unit tests"
```

---

## Task 3: Backend — `VoiceConfigDto.narrator_mode` + legacy translator

**Files:**
- Modify: `shared/dtos/persona.py`
- Create: `tests/modules/persona/test_voice_config_legacy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/modules/persona/__init__.py` (empty file) and `tests/modules/persona/test_voice_config_legacy.py`:

```python
from shared.dtos.persona import VoiceConfigDto


def test_narrator_mode_defaults_to_off():
    cfg = VoiceConfigDto()
    assert cfg.narrator_mode == "off"


def test_narrator_mode_accepts_valid_values():
    for v in ("off", "play", "narrate"):
        assert VoiceConfigDto(narrator_mode=v).narrator_mode == v


def test_legacy_roleplay_mode_true_translates_to_play():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": True})
    assert cfg.narrator_mode == "play"


def test_legacy_roleplay_mode_false_translates_to_off():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": False})
    assert cfg.narrator_mode == "off"


def test_narrator_mode_takes_precedence_over_legacy_flag():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": True, "narrator_mode": "narrate"})
    assert cfg.narrator_mode == "narrate"


def test_legacy_flag_is_not_re_emitted():
    cfg = VoiceConfigDto.model_validate({"roleplay_mode": True})
    dumped = cfg.model_dump()
    assert "roleplay_mode" not in dumped
    assert dumped["narrator_mode"] == "play"
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
mkdir -p tests/modules/persona
uv run pytest tests/modules/persona/test_voice_config_legacy.py -v
```

Expected: FAIL — `VoiceConfigDto` has no `narrator_mode` attribute.

- [ ] **Step 3: Update the DTO**

In `shared/dtos/persona.py`:

1. Add `model_validator` to the pydantic import at the top:

```python
from pydantic import BaseModel, Field, model_validator
```

2. Replace the current `VoiceConfigDto` class (currently lines 21-25) with:

```python
class VoiceConfigDto(BaseModel):
    dialogue_voice: str | None = None
    narrator_voice: str | None = None
    auto_read: bool = False
    narrator_mode: Literal["off", "play", "narrate"] = "off"

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_roleplay_mode(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "narrator_mode" in data:
            data.pop("roleplay_mode", None)
            return data
        legacy = data.pop("roleplay_mode", None)
        if legacy is True:
            data["narrator_mode"] = "play"
        elif legacy is False:
            data["narrator_mode"] = "off"
        return data
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/modules/persona/test_voice_config_legacy.py -v`
Expected: PASS (six tests).

- [ ] **Step 5: Run the full persona test suite for regressions**

Run: `uv run pytest tests/test_personas.py -v`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/persona.py tests/modules/persona/__init__.py tests/modules/persona/test_voice_config_legacy.py
git commit -m "Replace VoiceConfigDto.roleplay_mode with narrator_mode enum and legacy translator"
```

---

## Task 4: Backend — add `narrator_voice_id` to `mistral_voice` persona_config_fields

**Files:**
- Modify: `backend/modules/integrations/_registry.py`
- Modify: `tests/modules/integrations/test_registry_capabilities.py`

- [ ] **Step 1: Extend the test**

Append the following to `tests/modules/integrations/test_registry_capabilities.py`:

```python
def test_mistral_voice_has_narrator_voice_field():
    defn = get("mistral_voice")
    field = next(f for f in defn.persona_config_fields if f["key"] == "narrator_voice_id")
    assert field["field_type"] == "select"
    assert field["required"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/integrations/test_registry_capabilities.py -v`
Expected: FAIL — `StopIteration` because no field with `key == "narrator_voice_id"` exists.

- [ ] **Step 3: Extend the registry entry**

In `backend/modules/integrations/_registry.py` (around lines 187-196), replace the `persona_config_fields` list with:

```python
        persona_config_fields=[
            {
                "key": "voice_id",
                "label": "Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": True,
                "description": "Voice used when this persona speaks.",
            },
            {
                "key": "narrator_voice_id",
                "label": "Narrator Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": False,
                "description": "Voice used for narration / prose when narrator mode is active. Leave at 'Inherit' to use the primary voice.",
            },
        ],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/modules/integrations/test_registry_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_registry.py tests/modules/integrations/test_registry_capabilities.py
git commit -m "Add narrator_voice_id to mistral_voice persona_config_fields"
```

---

## Task 5: Frontend plugin — serve narrator voice list with Inherit option

**Files:**
- Modify: `frontend/src/features/integrations/plugins/mistral_voice/index.ts`

- [ ] **Step 1: Replace `getPersonaConfigOptions`**

In `frontend/src/features/integrations/plugins/mistral_voice/index.ts`, replace the current `getPersonaConfigOptions` method (lines 41-48) with:

```ts
  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    const apiKey = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
    if (apiKey) {
      await refreshMistralVoices(apiKey)
    }
    const voiceOptions = mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
    if (fieldKey === 'narrator_voice_id') {
      return [{ value: null, label: 'Inherit from primary voice' }, ...voiceOptions]
    }
    return voiceOptions
  },
```

- [ ] **Step 2: Verify `Option` type allows `value: null`**

Open `frontend/src/features/integrations/types.ts`, locate the `Option` type. If `value` is currently `string`, broaden it to `string | null`:

```ts
export interface Option { value: string | null; label: string }
```

If it is already broad enough, no change.

- [ ] **Step 3: Full typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors in this file (pre-existing errors from Task 1 still permitted; they get resolved later).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/integrations/plugins/mistral_voice/index.ts frontend/src/features/integrations/types.ts
git commit -m "Serve narrator voice options with Inherit entry in mistral_voice plugin"
```

---

## Task 6: Frontend types — `PersonaDto.voice_config.narrator_mode`

**Files:**
- Modify: `frontend/src/core/types/persona.ts`

- [ ] **Step 1: Update the `voice_config` shape**

In `frontend/src/core/types/persona.ts` (around lines 39-44), replace:

```ts
    roleplay_mode: boolean
```

with:

```ts
    narrator_mode: 'off' | 'play' | 'narrate'
```

So the full block reads:

```ts
  voice_config?: {
    dialogue_voice: string | null
    narrator_voice: string | null
    auto_read: boolean
    narrator_mode: 'off' | 'play' | 'narrate'
  } | null;
```

- [ ] **Step 2: Typecheck (expect errors in `PersonaVoiceConfig.tsx` and `ChatView.tsx`)**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: errors referencing `roleplay_mode` in `PersonaVoiceConfig.tsx` and `ChatView.tsx`. These are fixed in Tasks 7-9.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/types/persona.ts
git commit -m "Frontend PersonaDto: voice_config.narrator_mode replaces roleplay_mode"
```

---

## Task 7: `ReadAloudButton` — centralised state, narrator voice, cache key

**Files:**
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Replace the file**

Replace the contents of `frontend/src/features/voice/components/ReadAloudButton.tsx` with:

```tsx
import { useCallback, useEffect, useState } from 'react'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { parseForSpeech } from '../pipeline/audioParser'
import { readAloudCacheKey } from '../pipeline/readAloudCacheKey'
import type { NarratorMode, SpeechSegment, VoicePreset } from '../types'
import { useSecretsStore } from '../../integrations/secretsStore'
import { useIntegrationsStore } from '../../integrations/store'
import type { PersonaDto } from '../../../core/types/persona'
import { useNotificationStore } from '../../../core/store/notificationStore'

interface ReadAloudButtonProps {
  messageId: string
  content: string
  persona?: PersonaDto | null
  dialogueVoice?: VoicePreset
  narratorVoice?: VoicePreset
  mode?: NarratorMode
}

type ReadState = 'idle' | 'synthesising' | 'playing'

// ── Global active-reader state ──
// Only one ReadAloudButton (or auto-read trigger) is active at a time.
// Both activeMessageId and activeState are kept together so buttons render
// the correct indicator regardless of which entry point drove them.

type Listener = () => void
let activeMessageId: string | null = null
let activeState: ReadState = 'idle'
const listeners = new Set<Listener>()

export function setActiveReader(id: string | null, state: ReadState): void {
  activeMessageId = id
  activeState = state
  listeners.forEach((fn) => fn())
}

function useActiveReader(messageId: string): { isActive: boolean; state: ReadState } {
  const [snapshot, setSnapshot] = useState(() => ({
    isActive: activeMessageId === messageId,
    state: activeState,
  }))
  useEffect(() => {
    const update = () => setSnapshot({ isActive: activeMessageId === messageId, state: activeState })
    listeners.add(update)
    update()
    return () => { listeners.delete(update) }
  }, [messageId])
  return snapshot
}

// ── LRU cache ──

interface CachedAudio {
  segments: Array<{ audio: Float32Array; segment: SpeechSegment }>
}

const CACHE_MAX = 8
const cache = new Map<string, CachedAudio>()

function cacheGet(key: string): CachedAudio | undefined {
  const entry = cache.get(key)
  if (entry) { cache.delete(key); cache.set(key, entry) }
  return entry
}

function cachePut(key: string, entry: CachedAudio): void {
  cache.delete(key)
  cache.set(key, entry)
  if (cache.size > CACHE_MAX) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
}

// ── Shared synthesis runner ──

async function runReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
): Promise<void> {
  const tts = ttsRegistry.active()
  if (!tts?.isReady()) { setActiveReader(null, 'idle'); return }

  const cacheKey = readAloudCacheKey(messageId, primary.id, narratorVoiceId, mode)

  audioPlayback.setCallbacks({
    onSegmentStart: () => { if (activeMessageId === messageId) setActiveReader(messageId, 'playing') },
    onFinished: () => { if (activeMessageId === messageId) setActiveReader(null, 'idle') },
  })

  const cached = cacheGet(cacheKey)
  if (cached) {
    setActiveReader(messageId, 'playing')
    for (const { audio, segment } of cached.segments) {
      audioPlayback.enqueue(audio, segment)
    }
    return
  }

  const parsed = parseForSpeech(content, mode)
  if (parsed.length === 0) { setActiveReader(null, 'idle'); return }

  setActiveReader(messageId, 'synthesising')

  try {
    const results: CachedAudio['segments'] = []
    for (const segment of parsed) {
      if (activeMessageId !== messageId) return // cancelled
      const voice = segment.type === 'voice' ? primary : narrator
      const audio = await tts.synthesise(segment.text, voice)
      if (activeMessageId !== messageId) return
      results.push({ audio, segment })
      audioPlayback.enqueue(audio, segment)
    }
    cachePut(cacheKey, { segments: results })
  } catch (err) {
    if (activeMessageId !== messageId) return
    console.error('[ReadAloud] TTS synthesis failed:', err)
    setActiveReader(null, 'idle')
    const isAuthError = err instanceof Error && (err.message.includes('401') || err.message.includes('Unauthorized'))
    useNotificationStore.getState().addNotification({
      level: 'error',
      title: 'Read aloud failed',
      message: isAuthError
        ? "Couldn't read reply aloud — check your Mistral API key."
        : "Couldn't read reply aloud — check the console for details.",
    })
  }
}

// ── Imperative trigger for auto-read ──

/**
 * Trigger read-aloud for a message programmatically. Drives the same global
 * state and cache as the manual click path.
 */
export async function triggerReadAloud(
  messageId: string,
  content: string,
  primary: VoicePreset,
  narrator: VoicePreset,
  narratorVoiceId: string | null,
  mode: NarratorMode,
): Promise<void> {
  audioPlayback.stopAll()
  setActiveReader(messageId, 'synthesising')
  await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, mode)
}

// ── Component ──

export function ReadAloudButton({ messageId, content, persona, dialogueVoice, narratorVoice, mode }: ReadAloudButtonProps) {
  useSecretsStore((s) => s.secrets)
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const { isActive, state } = useActiveReader(messageId)

  const activeTTS = definitions.find(
    (d) => d.capabilities?.includes('tts_provider') && configs?.[d.id]?.enabled,
  )
  const ttsReady = ttsRegistry.active()?.isReady() === true
  const integrationCfg = activeTTS ? persona?.integration_configs?.[activeTTS.id] : undefined
  const voiceId = (integrationCfg?.voice_id as string | undefined) ?? undefined
  const narratorVoiceId = (integrationCfg?.narrator_voice_id as string | null | undefined) ?? null
  const resolvedMode: NarratorMode = mode ?? persona?.voice_config?.narrator_mode ?? 'off'

  const handleClick = useCallback(async () => {
    if (isActive && state !== 'idle') {
      audioPlayback.stopAll()
      setActiveReader(null, 'idle')
      return
    }

    audioPlayback.stopAll()

    const tts = ttsRegistry.active()
    if (!tts) {
      console.warn('[ReadAloud] No TTS engine active')
      return
    }

    const personaVoice = voiceId ? tts.voices.find((v) => v.id === voiceId) : undefined
    const primary = dialogueVoice ?? personaVoice
    if (!primary) {
      console.warn('[ReadAloud] No voice resolved')
      return
    }

    const personaNarrator = narratorVoiceId ? tts.voices.find((v) => v.id === narratorVoiceId) : undefined
    const narrator: VoicePreset = narratorVoice ?? personaNarrator ?? primary

    setActiveReader(messageId, 'synthesising')
    await runReadAloud(messageId, content, primary, narrator, narratorVoiceId, resolvedMode)
  }, [messageId, content, dialogueVoice, narratorVoice, resolvedMode, isActive, state, voiceId, narratorVoiceId])

  if (!ttsReady || !voiceId) return null

  const displayState = isActive ? state : 'idle'
  const label = displayState === 'synthesising' ? 'Preparing...' : displayState === 'playing' ? 'Stop' : 'Read'
  const active = displayState !== 'idle'

  return (
    <button type="button" onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${active ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
      title={label}>
      {displayState === 'synthesising' ? (
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-gold/30 border-t-gold" />
      ) : displayState === 'playing' ? (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" /></svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
      )}
      {label}
    </button>
  )
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: remaining errors only in `ChatView.tsx` (old `triggerReadAloud` signature) and `PersonaVoiceConfig.tsx` (old `roleplay_mode`). Fixed in Tasks 8-9.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/components/ReadAloudButton.tsx
git commit -m "Centralise read-aloud state, add narrator voice routing and cache key"
```

---

## Task 8: `ChatView` auto-read — pass `narrator_mode`, primary, narrator, narrator id

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Inspect the current auto-read block**

Run: `cd frontend && rg -n "triggerReadAloud|roleplayMode|activeTTS|ttsRegistry" src/features/chat/ChatView.tsx | head -30`

Look at the block around the `triggerReadAloud` call (near line 668) to confirm the in-scope variable names (`lastAssistant`, `voice`, `persona`, the active TTS id variable).

- [ ] **Step 2: Update the auto-read effect**

In `frontend/src/features/chat/ChatView.tsx`, inside the auto-read `useEffect`, replace:

```tsx
      const roleplayMode = !!persona?.voice_config?.roleplay_mode

      void triggerReadAloud(lastAssistant.id, lastAssistant.content, voice, roleplayMode)
```

with:

```tsx
      const narratorMode = persona?.voice_config?.narrator_mode ?? 'off'
      const ttsDefn = intDefinitions.find((d) => d.capabilities?.includes('tts_provider') && intConfigs?.[d.id]?.enabled)
      const narratorVoiceId = ttsDefn
        ? ((persona?.integration_configs?.[ttsDefn.id]?.narrator_voice_id as string | null | undefined) ?? null)
        : null
      const tts = ttsRegistry.active()
      const narratorVoice = narratorVoiceId
        ? (tts?.voices.find((v) => v.id === narratorVoiceId) ?? voice)
        : voice

      void triggerReadAloud(lastAssistant.id, lastAssistant.content, voice, narratorVoice, narratorVoiceId, narratorMode)
```

If the variable holding the integration definitions is not `intDefinitions` or the configs is not `intConfigs` in this file, adjust to the local names (already imported at the top of the file as the other auto-read code uses them).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors in `ChatView.tsx` (remaining errors only in `PersonaVoiceConfig.tsx`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Auto-read: pass narrator mode and narrator voice to triggerReadAloud"
```

---

## Task 9: `PersonaVoiceConfig` — mode dropdown, narrator voice field, preview buttons

**Files:**
- Modify: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`

- [ ] **Step 1: Replace the component**

Replace the contents of `frontend/src/features/voice/components/PersonaVoiceConfig.tsx` with:

```tsx
import { useCallback, useState } from 'react'
import type { PersonaDto } from '../../../core/types/persona'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import { useIntegrationsStore } from '../../integrations/store'
import { useSecretsStore } from '../../integrations/secretsStore'
import { getPlugin } from '../../integrations/registry'
import { GenericConfigForm } from '../../integrations/components/GenericConfigForm'
import { ttsRegistry } from '../engines/registry'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { setActiveReader } from './ReadAloudButton'
import type { NarratorMode } from '../types'

interface Props {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
}

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'
const TTS_PROVIDER = 'tts_provider'
const PREVIEW_PHRASE = 'The quick brown fox jumps over the lazy dog.'

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

const MODE_LABELS: Record<NarratorMode, string> = {
  off: 'Off',
  play: 'Roleplay (dialogue spoken)',
  narrate: 'Narrated (narration spoken)',
}

export function PersonaVoiceConfig({ persona, chakra, onSave }: Props) {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const [autoRead, setAutoRead] = useState<boolean>(
    persona.voice_config?.auto_read ?? false,
  )
  const [narratorMode, setNarratorMode] = useState<NarratorMode>(
    persona.voice_config?.narrator_mode ?? 'off',
  )
  const [saving, setSaving] = useState(false)

  const activeTTS = definitions.find(
    (d) => d.capabilities?.includes(TTS_PROVIDER) && configs?.[d.id]?.enabled,
  )
  const ttsPlugin = activeTTS ? getPlugin(activeTTS.id) : undefined
  const secrets = useSecretsStore((s) => s.secrets)

  const optionsProvider = useCallback(
    (fieldKey: string) =>
      ttsPlugin?.getPersonaConfigOptions?.(fieldKey) ?? Promise.resolve([]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ttsPlugin, secrets],
  )

  const persistVoiceConfig = useCallback(
    async (patch: Partial<{ auto_read: boolean; narrator_mode: NarratorMode }>) => {
      setSaving(true)
      try {
        await onSave(persona.id, {
          voice_config: {
            dialogue_voice: persona.voice_config?.dialogue_voice ?? null,
            narrator_voice: persona.voice_config?.narrator_voice ?? null,
            auto_read: autoRead,
            narrator_mode: narratorMode,
            ...patch,
          },
        })
      } finally {
        setSaving(false)
      }
    },
    [persona.id, persona.voice_config, onSave, autoRead, narratorMode],
  )

  const handleAutoReadChange = useCallback(
    async (value: boolean) => {
      setAutoRead(value)
      await persistVoiceConfig({ auto_read: value })
    },
    [persistVoiceConfig],
  )

  const handleModeChange = useCallback(
    async (value: NarratorMode) => {
      setNarratorMode(value)
      await persistVoiceConfig({ narrator_mode: value })
    },
    [persistVoiceConfig],
  )

  // Preview: synthesises PREVIEW_PHRASE with the selected voice. Does not
  // participate in activeMessageId tracking; stopAll is always called first,
  // which cancels any ongoing read-aloud or earlier preview.
  const playPreview = useCallback(async (voiceId: string) => {
    const tts = ttsRegistry.active()
    if (!tts?.isReady()) return
    const voice = tts.voices.find((v) => v.id === voiceId)
    if (!voice) return
    audioPlayback.stopAll()
    setActiveReader(null, 'idle')
    try {
      const audio = await tts.synthesise(PREVIEW_PHRASE, voice)
      audioPlayback.setCallbacks({ onSegmentStart: () => {}, onFinished: () => {} })
      audioPlayback.enqueue(audio, { type: 'voice', text: PREVIEW_PHRASE })
    } catch (err) {
      console.error('[PersonaVoiceConfig] Preview failed:', err)
    }
  }, [])

  const showNarratorField = narratorMode !== 'off'

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Configure how this persona speaks. Enable a TTS integration and select a voice below.
      </p>

      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-[12px] text-white/70 font-mono">Auto-Read Replies</span>
            <p className="text-[10px] text-white/35 font-mono mt-0.5">
              Automatically speak each reply as it arrives.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={autoRead}
            disabled={saving}
            onClick={() => handleAutoReadChange(!autoRead)}
            className="relative flex-shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50"
            style={{ width: 44, height: 20, background: autoRead ? chakra.hex : 'rgba(255,255,255,0.1)' }}
          >
            <span
              className="absolute top-[2px] rounded-full bg-white shadow transition-transform duration-200"
              style={{ width: 16, height: 16, left: 2, transform: autoRead ? 'translateX(24px)' : 'translateX(0)' }}
            />
          </button>
        </div>

        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <span className="text-[12px] text-white/70 font-mono">Narrator Mode</span>
            <p className="text-[10px] text-white/35 font-mono mt-0.5">
              Split prose and dialogue into two voices.
            </p>
          </div>
          <select
            value={narratorMode}
            disabled={saving}
            onChange={(e) => handleModeChange(e.target.value as NarratorMode)}
            className="bg-white/5 text-[12px] font-mono text-white/80 rounded px-2 py-1 border border-white/10 focus:border-white/30 focus:outline-none disabled:opacity-50"
          >
            <option value="off" style={OPTION_STYLE}>{MODE_LABELS.off}</option>
            <option value="play" style={OPTION_STYLE}>{MODE_LABELS.play}</option>
            <option value="narrate" style={OPTION_STYLE}>{MODE_LABELS.narrate}</option>
          </select>
        </div>
      </div>

      <div>
        <label className={LABEL}>Voice</label>
        {!activeTTS && (
          <p className="text-[11px] text-white/40 font-mono leading-relaxed">
            Activate a TTS integration under Settings → Integrations to select a voice for this persona.
          </p>
        )}
        {activeTTS && (
          <VoiceFormWithPreview
            activeTTS={activeTTS}
            persona={persona}
            optionsProvider={optionsProvider}
            onSave={onSave}
            playPreview={playPreview}
            showNarratorField={showNarratorField}
          />
        )}
      </div>
    </div>
  )
}

function VoiceFormWithPreview({
  activeTTS, persona, optionsProvider, onSave, playPreview, showNarratorField,
}: {
  activeTTS: { id: string; persona_config_fields: Array<{ key: string }> }
  persona: PersonaDto
  optionsProvider: (fieldKey: string) => Promise<Array<{ value: string | null; label: string }>>
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
  playPreview: (voiceId: string) => Promise<void>
  showNarratorField: boolean
}) {
  const initial = (persona.integration_configs?.[activeTTS.id] ?? {}) as Record<string, unknown>
  const primaryId = initial.voice_id as string | undefined
  const narratorId = initial.narrator_voice_id as string | null | undefined

  const fields = (activeTTS.persona_config_fields).filter(
    (f) => f.key !== 'narrator_voice_id' || showNarratorField,
  )

  return (
    <div className="flex flex-col gap-2">
      <GenericConfigForm
        fields={fields as typeof activeTTS.persona_config_fields}
        initialValues={initial}
        onSubmit={async (values) => {
          await onSave(persona.id, {
            integration_configs: {
              ...(persona.integration_configs ?? {}),
              [activeTTS.id]: values,
            },
          })
        }}
        optionsProvider={optionsProvider}
        submitLabel="Save voice"
        autoSubmit
      />
      <div className="flex flex-col gap-2 mt-1">
        {primaryId && (
          <PreviewButton label="Preview primary voice" onClick={() => playPreview(primaryId)} />
        )}
        {showNarratorField && narratorId && (
          <PreviewButton label="Preview narrator voice" onClick={() => playPreview(narratorId)} />
        )}
      </div>
    </div>
  )
}

function PreviewButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-2 self-start text-[10px] font-mono text-white/45 hover:text-white/75 transition-colors"
    >
      <svg width="11" height="11" viewBox="0 0 14 14" fill="none">
        <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
        <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
      </svg>
      {label}
    </button>
  )
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors. If `VoiceFormWithPreview`'s prop typing is too loose, tighten against the real `IntegrationDto` type imported from `frontend/src/features/integrations/types.ts`.

- [ ] **Step 3: Build**

Run: `cd frontend && pnpm run build`
Expected: build passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/components/PersonaVoiceConfig.tsx
git commit -m "PersonaVoiceConfig: narrator mode dropdown, narrator voice field, preview"
```

---

## Task 10: Full test suites + manual verification

**Files:** None (verification task).

- [ ] **Step 1: Backend tests**

Run: `uv run pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 2: Frontend tests**

Run: `cd frontend && pnpm vitest run`
Expected: PASS (audio parser + cache key + any other existing tests).

- [ ] **Step 3: Frontend typecheck + build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: PASS.

- [ ] **Step 4: Manual verification (user runs in dev env)**

Check each of the following. If any fails, file the symptom and fix before merging.

- Stream a reply with auto-read on, narrator mode off — button on the message shows spinner then stop-icon; clicking it during synthesis cancels synthesis; clicking during playback stops playback.
- Change the persona's primary voice, click read on the same message again — new audio is synthesised (not the old cached take).
- Set narrator mode to `Roleplay (dialogue spoken)`, pick a distinct narrator voice, send a message with mixed `"..."` and `*...*` — playback alternates voices.
- Set narrator mode to `Narrated (narration spoken)` — roles invert: `*...*` goes to the narrator, `"..."` to the persona.
- Leave narrator voice at "Inherit from primary voice" — playback uses the primary voice for both roles (single-voice output).
- Click "Preview primary voice" and "Preview narrator voice" — each plays the test phrase with the selected voice; clicking one interrupts the other; clicking any `ReadAloudButton` interrupts the preview.
- Reload a persona whose stored document still has `roleplay_mode: true` (local dev fixture) — the UI shows `Roleplay (dialogue spoken)` and the persona round-trips without error.

- [ ] **Step 5: Final commit (if any touchup required)**

If Step 4 required a fix, commit with a descriptive message. Otherwise no commit is needed.

---

## Post-Implementation

- Merge the feature branch back into `master` — the project default per CLAUDE.md is to merge after implementation.
- File a follow-up spec for sentence-by-sentence streaming (the deferred "big" change), building on the `readAloudCacheKey` helper and the centralised state introduced here.
