# Integration Inline-Triggers — Foundation Design

**Date:** 2026-04-30
**Status:** Approved (pre-implementation)
**Scope:** Foundation only. The Screen Effects integration that consumes this foundation is out of scope and lives in a follow-up session.

---

## Background

Chatsune already supports two orthogonal in-stream tag systems:

- **xAI voice expression tags** (`[laugh]`, `<whisper>` etc.) — detected in the TTS sentencer pipeline (`frontend/src/features/voice/pipeline/audioParser.ts`), stripped from the synth feed and rendered as inline pills in chat. Source of truth: `backend/modules/integrations/_voice_expression_tags.py` and `frontend/src/features/voice/expressionTags.ts`.
- **Integration response tags** (`<lovense vibrate 5>`) — detected in the front-end `ResponseTagBuffer` (`frontend/src/features/integrations/responseTagProcessor.ts`) before the sentencer, executed via plugin code, and rendered using the plugin's free-form `displayText`.

Neither system supports **frontend-side effects that fire in lockstep with sentence-level TTS playback**. Upcoming integrations (starting with Screen Effects: emoji showers, visual flourishes, "demo-scener" effects) need exactly that capability.

This spec defines the foundation that future "inline-trigger" integrations will consume. The actual Screen Effects integration is built on top of this in a follow-up session.

---

## Goals

1. Allow an integration to declare commands of the form `<integration_id command args...>` in the LLM stream, have them excluded from TTS, rendered as uniform inline pills, and trigger frontend events.
2. Synchronise effect events with sentence-by-sentence TTS playback when the integration requests it; fire immediately otherwise.
3. Use a single catch-all topic so any integration can hook into the same dispatch mechanism.
4. Allow an integration to be enabled by default for all users (with explicit opt-out still possible).
5. Decouple integration system-prompt extensions from the `tools_enabled` flag so non-tool integrations can extend the prompt unconditionally.
6. Make manual re-triggering through the existing "Read Aloud" / "Auto Read Aloud" UI work without additional code paths.

## Non-Goals

- Building the Screen Effects integration itself, its tag vocabulary, or its frontend renderer component.
- Per-persona override of integration enablement (deferred — see "Future Migration Paths").
- Backend-side audit logging of inline triggers (deferred — topic lives in `shared/` so this is additive later).
- Migrating the xAI voice-expression tag pills onto the new `IntegrationPill` component (kept on its existing renderer; only CSS tokens are shared).

---

## Design Decisions (Resolved during Brainstorming)

| # | Decision | Rationale |
|---|---|---|
| 1 | Persona relationship: **voice-provider style** (`assignable=False`) | Screen Effects-style integrations are UX features, not tools. One global toggle per user, active across all personas. Future per-persona override remains possible (see Future Migration Paths). |
| 2 | Default-on mechanic: **lazy default in read logic** via new `IntegrationDefinition.default_enabled: bool = False` | No DB migration; "default" is a product property of the code, not user state. |
| 3 | Tag-to-effect detection: **frontend-only pipeline** | Consistent with existing patterns; Read-Aloud re-trigger works automatically; backend stays agnostic. |
| 4 | Pill rendering: **strict-uniform** — all integrations route through a single `IntegrationPill` component | Maximum visual consistency; Lovense is migrated alongside. |
| 5 | `tools_enabled` gate: **heuristic via `tool_definitions`** | Information already structured; no redundant flag per integration. |
| 6 | Topic name: `INTEGRATION_INLINE_TRIGGER` in `shared/topics.py` | Semantically distinct from `INTEGRATION_ACTION_EXECUTED` (audit) and generic enough for future trigger types. |

Additional decision captured during architecture review:

- **`syncWithTts` is plugin-decision flag, not mode detection.** Each plugin decides per execution whether the effect should bind to the sentence-start callback or fire immediately. Allows an integration to mix immediate and synchronised effects in one stream.
- **Source-of-trigger field** on the event: `'live_stream' | 'text_only' | 'read_aloud'`. Consumers may use it to vary behaviour (e.g. duration) on re-trigger.

---

## Architecture & Data Flow

### Voice mode (TTS active)

```
Backend LLM stream:    "...sehr gut! <screen_effects emojishower 💖🔥> Wie geht's?"
        ↓
ChatContentDeltaEvent (CHAT_CONTENT_DELTA)
        ↓
useChatStream → ResponseTagBuffer (streamSource='live_stream')
        ├─ Tag detected, plugin.executeTag() returns
        │  {pillContent, syncWithTts: true, effectPayload}
        ├─ generates UUID, replaces tag with placeholder ​[effect:UUID]​
        ├─ stores {UUID → effect metadata} in pendingEffectsMap
        ↓
Sentencer accumulates until safe-cut
        ↓
audioParser.parseForSpeech(sentenceText, pendingEffectsMap)
        ├─ strips voice expression tags for synth
        ├─ extracts effect placeholders, looks up payloads in pendingEffectsMap
        ├─ attaches payloads to SpeechSegment.effects[]
        ↓
SpeechSegment {text, effects: [{...}]}
        ↓
audioPlayback.enqueue(audio, segment, source='live_stream')
        ↓
playNext() → onSegmentStart(segment) just before source.start(0)
        ↓
playbackChild emits eventBus.emit(INTEGRATION_INLINE_TRIGGER, {..., source: 'live_stream'})
        ↓
Subscribers (e.g. ScreenEffectsRenderer) act
```

### Text-only mode (no TTS pipeline)

```
ResponseTagBuffer (streamSource='text_only') detects tag
        ↓
plugin.executeTag() returns {syncWithTts: anything}
        ↓
ResponseTagBuffer emits INTEGRATION_INLINE_TRIGGER immediately (source='text_only')
Pill placeholder remains in stream for IntegrationPill rendering
```

Note: in text-only mode, even `syncWithTts=true` fires immediately — there is no sentence-start callback to synchronise to. This is the "the persona just speaks that fast" mental model.

### Read-Aloud / Auto Read-Aloud

`ReadAloudButton.tsx`:

1. Fetches the original message content (still containing `<integration_id ...>` tags as stored by the backend)
2. Runs a fresh `ResponseTagBuffer(streamSource='read_aloud')` over it
3. Passes the placeholder-containing output to `parseForSpeech`
4. Calls `audioPlayback.enqueue(..., source='read_aloud')`
5. → `onSegmentStart` fires events with `source: 'read_aloud'`

Re-triggering works without any additional code path because the same parsing pipeline is reused.

---

## Backend Components

### B1. `IntegrationDefinition` extension

`backend/modules/integrations/_models.py`

Add one field:

```python
@dataclass(frozen=True)
class IntegrationDefinition:
    # … existing fields …
    default_enabled: bool = False
```

The existing `response_tag_prefix` field is sufficient to flag inline-pill participation; no further field is required.

### B2. `effective_enabled_map` update

`backend/modules/integrations/__init__.py:37-72`

Replace the unlinked-integration branch with explicit default handling:

```python
cfg = cfg_map.get(iid)
if cfg is None:
    result[iid] = defn.default_enabled
else:
    result[iid] = bool(cfg.get("enabled", False))
```

Premium-linked integrations remain unchanged. An explicit user-stored `enabled` value (True or False) always wins over `default_enabled`.

### B3. Prompt assembler refactor

`backend/modules/chat/_prompt_assembler.py:118-140`

Replace the binary `if tools_enabled:` block with a heuristic pass:

```python
from backend.modules.integrations import (
    get_enabled_integration_ids,
    get_integration,
)

enabled_ids = await get_enabled_integration_ids(user_id, persona_id)
extensions: list[str] = []
for iid in enabled_ids:
    defn = get_integration(iid)
    if not defn or not defn.system_prompt_template:
        continue
    has_tools = bool(defn.tool_definitions)
    if has_tools and not tools_enabled:
        # Tool-using integration's prompt explains tool calls — irrelevant when tools are off
        continue
    extensions.append(defn.system_prompt_template)

if extensions:
    parts.append("\n\n".join(extensions))

if not tools_enabled:
    parts.append('<toolavailability priority="high">…</toolavailability>')
```

The "no tools available" block is preserved verbatim — it is orthogonal to extension injection.

### B4. Topic and event DTO

`shared/topics.py` — add:

```python
INTEGRATION_INLINE_TRIGGER = "integration.inline.trigger"
```

`shared/events/integrations.py` — add:

```python
class IntegrationInlineTriggerEvent(BaseModel):
    integration_id: str
    command: str
    args: list[str]
    payload: Any
    source: Literal["live_stream", "text_only", "read_aloud"]
    correlation_id: str
    timestamp: datetime
```

The backend never emits this event in the foundation scope — the topic is reserved so future backend-side audit logging is a non-breaking addition.

---

## Frontend Components

### F1. Plugin interface extension

`frontend/src/features/integrations/types.ts`

Replace the existing `displayText`-only async result with a **synchronous** decision plus an optional async side-effect:

```typescript
export interface TagExecutionResult {
  pillContent: string                  // text shown in the inline pill (sync)
  syncWithTts: boolean                 // bind to sentence-start callback when true (sync)
  effectPayload: unknown               // free, plugin-specific (sync)
  sideEffect?: () => Promise<void>     // optional async work (e.g. hardware API call); fire-and-log
}
```

Plugin implementations of `executeTag` change from `Promise<TagExecutionResult>` to synchronous `TagExecutionResult`. Async side-effects (e.g. Lovense's HTTP call to the local toy API) live in the optional `sideEffect` thunk; `ResponseTagBuffer` invokes them without awaiting (errors are logged).

**Why sync result?** `pillContent` and `syncWithTts` must be known **before** the placeholder enters the sentencer pipeline — otherwise `pendingEffectsMap` would be empty when `audioParser` claims it at the sentence boundary, causing a race.

### F2. `ResponseTagBuffer` enhancement

`frontend/src/features/integrations/responseTagProcessor.ts`

Constructor signature changes:

```typescript
constructor(
  onTagResolved: (placeholder: string, replacement: string) => void,
  streamSource: 'live_stream' | 'text_only' | 'read_aloud',
  pendingEffectsMap: Map<string, PendingEffect>,
)
```

Per detected tag:

1. Generate UUID `effectId`
2. Replace tag in stream with placeholder `​[effect:${effectId}]​` (zero-width-space wrappers, exactly as the existing Lovense placeholder uses)
3. Call `plugin.executeTag(...)` **synchronously**, store `{effectId → {pillContent, effectPayload, integration_id, command, args}}` in `pendingEffectsMap`. If the result has a `sideEffect`, invoke it without awaiting (errors logged via `console.error` and an `IntegrationPill`-rendered error overlay if needed).
4. **Decide immediate vs deferred emit:**
    - `syncWithTts === false` → emit `INTEGRATION_INLINE_TRIGGER` **immediately**, remove entry from map. (Plugin requested unsynchronised behaviour, e.g. hardware trigger.)
    - `syncWithTts === true` AND `streamSource === 'text_only'` → emit immediately (no TTS pipeline to synchronise to)
    - `syncWithTts === true` AND `streamSource ∈ {'live_stream', 'read_aloud'}` → leave entry in map for `audioParser` to claim at sentence boundary (TTS pipeline is active in both cases)

Stream end: any entries still in the map at stream completion are flushed (immediate emit, preserving the original `source`). Stream abort: map is discarded.

### F3. `IntegrationPill` React component (NEW)

`frontend/src/features/integrations/IntegrationPill.tsx`

A minimal monospace pill. Used everywhere inline integration tags appear:

```tsx
export function IntegrationPill({ pillContent }: { pillContent: string }) {
  return <span className="integration-pill">{pillContent}</span>
}
```

CSS tokens shared with the existing voice-expression-tag pill (extracted into a common stylesheet). The Markdown / message renderer recognises `​[effect:UUID]​` placeholders and substitutes `IntegrationPill` with the `pillContent` resolved from `pendingEffectsMap` (live stream) or from a regenerated map (persisted messages).

### F4. `SpeechSegment` extension

`frontend/src/features/voice/types.ts`

Add the optional `effects` field:

```typescript
interface SpeechSegment {
  text: string
  type: 'voice' | 'narration'
  speed?: number
  pitch?: number
  effects?: IntegrationInlineTrigger[]   // new
}
```

### F5. `audioParser.parseForSpeech` extension

`frontend/src/features/voice/pipeline/audioParser.ts:8-11` (and surrounds)

Additionally:

- Detects placeholders matching `/​\[effect:([0-9a-f-]+)\]​/g`
- Strips them from the synth-bound text
- For each UUID, looks up `pendingEffectsMap`, takes the entry, attaches it to `segment.effects[]`
- Removes it from the map (segment now owns it)

### F6. `audioPlayback` / `playbackChild` trigger emit

`frontend/src/features/voice/infrastructure/audioPlayback.ts:201` and `frontend/src/features/voice/children/playbackChild.ts:18-23`

`onSegmentStart(segment)` fires `eventBus.emit(INTEGRATION_INLINE_TRIGGER, {...effect, source})` for every entry in `segment.effects ?? []`.

`audioPlayback.enqueue` signature is extended to take a `source: 'live_stream' | 'read_aloud'` argument; `onSegmentStart` passes it through.

### F7. `ReadAloudButton` re-trigger path

`frontend/src/features/<…>/ReadAloudButton.tsx:128-146`

Wraps `parseForSpeech` with a fresh `ResponseTagBuffer(streamSource='read_aloud', pendingEffectsMap)` over the original message content. Calls `audioPlayback.enqueue(..., source='read_aloud')`.

### F8. `useChatStream` source detection

`frontend/src/features/chat/useChatStream.ts:35` (where `ResponseTagBuffer` is currently constructed)

Determines the active stream source:

- If the current chat session is in voice mode (voice pipeline group active) → `streamSource: 'live_stream'`
- Otherwise → `streamSource: 'text_only'`

This information is passed to the `ResponseTagBuffer` constructor for the duration of the stream.

---

## Backwards Compatibility & Migration

| Change | Impact | Migration |
|---|---|---|
| `default_enabled: bool = False` | Default `False` → no behaviour change for existing integrations | None |
| `effective_enabled_map` rewrite | Identical result for `default_enabled=False` integrations | None |
| Prompt assembler refactor | With `tools_enabled=True`: identical. With `tools_enabled=False`: non-tool integrations' extensions are now injected (intended new behaviour) | None |
| `displayText` → `pillContent` in `TagExecutionResult` (and `executeTag` becoming sync; async work moves to `sideEffect`) | Lovense plugin requires code change: rewrite `executeTag` from async to sync, move HTTP toy-API call into `sideEffect`, return `pillContent` instead of Markdown `displayText` | Frontend code edit only |
| Placeholder format change (`​[id:cmd]​` → `​[effect:UUID]​`) | Persisted message content is unaffected (backend stores original tag text); only in-flight stream representation changes | None |

No DB-schema-affecting changes. Compliant with the no-more-wipes mandate from `CLAUDE.md`.

---

## Testing Strategy

### Backend (pytest)

- `effective_enabled_map`:
  - No config doc + `default_enabled=True` → `True`
  - No config doc + `default_enabled=False` → `False`
  - Explicit doc `enabled=True` → `True` (regardless of `default_enabled`)
  - Explicit doc `enabled=False` → `False` (regardless of `default_enabled`)
- `_prompt_assembler.assemble`:
  - `has_tools=True, tools_enabled=True` → extension injected
  - `has_tools=True, tools_enabled=False` → extension skipped
  - `has_tools=False, tools_enabled=True` → extension injected
  - `has_tools=False, tools_enabled=False` → extension injected (key new behaviour)
  - "no tools available" block present if and only if `tools_enabled=False`

### Frontend (Vitest)

- `ResponseTagBuffer`:
  - Multiple occurrences of the same tag yield distinct UUID placeholders
  - `syncWithTts=true` + `streamSource='live_stream'` → entry stored in `pendingEffectsMap`, no immediate emit
  - `syncWithTts=true` + `streamSource='text_only'` → immediate emit (text-only forces immediate)
  - `syncWithTts=false` → immediate emit regardless of source
  - Stream end flushes residual map entries
- `audioParser`:
  - Effect placeholders are stripped from synth text
  - Effect entries land in `segment.effects[]` in encounter order
- `audioPlayback.onSegmentStart`:
  - Emits one event per `segment.effects[]` entry
  - Event carries the supplied `source`
- `ReadAloudButton`:
  - Re-running on a stored message produces events with `source: 'read_aloud'`
- `IntegrationPill`:
  - Renders supplied `pillContent` with the shared CSS class

---

## Manual Verification

To be performed on a real device (laptop + phone) by Chris before merge:

1. Stub a test plugin (`integration_id="test_inline"`, two commands: `sync` with `syncWithTts=true`, `now` with `syncWithTts=false`). Register it with `default_enabled=True`.
2. **Voice-mode live stream** — send a message that elicits a response containing both tags mid-sentence. Verify:
   - Pills visible in chat with monospace styling identical to xAI voice-tag pills
   - `sync` event fires precisely as the corresponding sentence starts speaking
   - `now` event fires as soon as the tag is parsed (before the sentence speaks)
3. **Text-only stream** — disable TTS, repeat. Both events fire as the tags are streamed in.
4. **Read-Aloud** — open the stored message from step 2, click Read Aloud. Verify events fire with `source: 'read_aloud'`, sentence-sync intact for `sync`.
5. **Auto-Read-Aloud** — enable Auto Read Aloud, send a fresh message with tags. Verify identical behaviour to step 2.
6. **Lovense visual regression** — send a message that triggers a Lovense tag. Verify the new `IntegrationPill` rendering looks acceptable; compare against pre-change screenshot.
7. **xAI voice-tag pills** — verify they remain visually consistent with `IntegrationPill` (same monospace font, comparable bg/fg).
8. **Default-enabled flip** — temporarily set `test_inline` to `default_enabled=False`, restart, verify it is off until explicitly enabled.
9. **Tool-disabled prompt** — disable tools on the persona; verify Lovense's prompt extension is gone but `xai_voice` extension is still present in the assembled prompt. Use the existing prompt preview path or inspect the system prompt sent to the LLM via debug logs.

---

## Edge Cases

| Case | Handling |
|---|---|
| Tag before first sentence | Stored in `pendingEffectsMap`; `audioParser` claims it on the first sentence's parse. |
| Tag after final sentence | At stream end, residual map entries are flushed (immediate emit with current `source`). Prevents lost effects. |
| Multiple tags in one sentence | Each gets its own UUID; each is stored independently in `segment.effects[]`; each fires separately on `onSegmentStart`. |
| Stream aborted | `pendingEffectsMap` discarded; no events fired for entries not yet claimed. |
| Plugin `executeTag` throws synchronously | Caught by `ResponseTagBuffer`; pill rendered with error content (e.g. `pillContent: "[error: …]"`); no event emitted; map entry not created. |
| Plugin `sideEffect` Promise rejects | Logged to console; does not affect pill rendering or event emission (pill and event are already locked in from the sync result). |
| Tag with unknown `integration_id` | Tag prefixes set does not match → tag passes through as plain text (status quo). |
| Re-trigger overlapping with live stream | Read-Aloud uses its own `pendingEffectsMap` and `audioPlayback` lifecycle — no interference. |
| Tag split across chunk boundaries | Already handled by `ResponseTagBuffer.process` buffering on `<` (status quo). |

---

## Future Migration Paths

Documented so future work has a clean starting point:

1. **Per-persona override (Model C from brainstorming)** — if user feedback drives a need for "this persona doesn't get screen effects", introduce `persona.integrations_config.disabled_integration_ids` (a negative-list field). Read path: `get_enabled_integration_ids` filters `default_enabled=True && assignable=False` integrations against the persona's disabled-list. Backwards-compatible because absence of the list means "no overrides".
2. **Backend audit logging** — emit `INTEGRATION_INLINE_TRIGGER` server-side when (or if) inline-trigger detection moves backend-side. Topic and DTO are already in `shared/`.
3. **Migrate xAI voice-expression pills onto `IntegrationPill`** — currently kept on its own renderer for risk reasons. If/when the audioParser-detected pills and ResponseTagBuffer-detected pills need to share more behaviour (e.g. accessibility, keyboard interaction), unify the renderer.

---

## File-Level Summary

**New files**
- `frontend/src/features/integrations/IntegrationPill.tsx`

**Backend changes**
- `backend/modules/integrations/_models.py` — `default_enabled` field
- `backend/modules/integrations/__init__.py` — `effective_enabled_map` branch
- `backend/modules/chat/_prompt_assembler.py` — extension heuristic
- `shared/topics.py` — `INTEGRATION_INLINE_TRIGGER`
- `shared/events/integrations.py` — `IntegrationInlineTriggerEvent`

**Frontend changes**
- `frontend/src/features/integrations/types.ts` — `TagExecutionResult` shape
- `frontend/src/features/integrations/responseTagProcessor.ts` — UUID placeholders, `streamSource`, `pendingEffectsMap`, immediate-vs-deferred emit
- `frontend/src/features/voice/pipeline/audioParser.ts` — placeholder strip + effect attach
- `frontend/src/features/voice/pipeline/streamingSentencer.ts` — `effects?` field on segment type
- `frontend/src/features/voice/infrastructure/audioPlayback.ts` — `source` parameter, segment-effects emit
- `frontend/src/features/voice/children/playbackChild.ts` — pass `source` through
- `frontend/src/features/chat/useChatStream.ts` — `streamSource` detection
- `frontend/src/features/<…>/ReadAloudButton.tsx` — pre-pipe through `ResponseTagBuffer`
- `frontend/src/features/integrations/<lovense plugin>` — switch `displayText` to `pillContent`
- Shared CSS tokens for inline pills

---

## Out of Scope (Foundation Session)

- Screen Effects integration plugin (`integration_id="screen_effects"`)
- Screen Effects renderer component (emoji shower, etc.)
- Tag vocabulary for Screen Effects
- Backend audit emission of `INTEGRATION_INLINE_TRIGGER`
- Per-persona override migration

These are addressed in the follow-up session that builds the actual Screen Effects experience on top of this foundation.
