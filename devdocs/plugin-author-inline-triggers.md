# Plugin Author Cookbook — Inline-Trigger Integrations

A short, pragmatic guide for adding a new integration that emits commands inline in the LLM stream and triggers something on the frontend (visual effect, hardware action, render hint, …).

**Foundation spec:** `devdocs/specs/2026-04-30-integration-inline-triggers-design.md`

**Canonical reference plugin:** Lovense (`frontend/src/features/integrations/plugins/lovense/`) — synchronous `executeTag`, hardware action in `sideEffect`, pill rendered through the shared `.integration-pill` CSS class.

---

## Concept in one paragraph

The LLM emits a tag of the form `<integration_id command arg1 arg2 ...>` somewhere in its visible response. The frontend `ResponseTagBuffer` recognises the tag, calls the plugin's `executeTag(command, args, config)` synchronously, and replaces the tag with a placeholder that the rehype plugin renders as an inline pill. A `Topics.INTEGRATION_INLINE_TRIGGER` event is emitted on the frontend event bus — either immediately (text mode or when the plugin asks for it) or in lockstep with sentence-level TTS playback (when both `syncWithTts: true` and TTS is active). Consumer components subscribe to the bus topic, filter by `integration_id`, and react. Tags inside the model's `thinking` block are automatically ignored — only chat content is parsed.

---

## Steps to add a new integration

### 1. Backend: register the `IntegrationDefinition`

`backend/modules/integrations/_registry.py` — append a `register(...)` call inside `_register_builtins()`. Relevant fields:

```python
register(IntegrationDefinition(
    id="my_integration",                       # unique slug, also the response tag prefix
    display_name="My Integration",
    description="What this does, one line.",
    icon="sparkles",                           # icon slug used in the IntegrationsTab
    execution_mode="frontend",                 # use "frontend" for purely-FE integrations
    config_fields=[],                          # user-configurable fields, often empty
    response_tag_prefix="my_integration",      # MUST equal id; turns on FE tag detection
    system_prompt_template=MY_PROMPT_BLOCK,    # see step 4
    tool_definitions=[],                       # empty for non-tool integrations
    default_enabled=True,                      # auto-on for every user without an explicit toggle
    assignable=False,                          # global per user; not per-persona
))
```

**Decision points:**

- `default_enabled`: `True` for "ambient" integrations the user opts out of; `False` for opt-in like Lovense.
- `assignable`: `False` for global behaviour (voice providers, screen effects); `True` if it should appear on a per-persona allowlist (Lovense).
- `tool_definitions`: leave empty for inline-trigger-only integrations. The prompt assembler's heuristic will inject your `system_prompt_template` regardless of `tools_enabled` exactly because there are no tools to gate on.

### 2. Frontend: register the plugin

`frontend/src/features/integrations/registry.ts` — register a plugin object with the matching `id`. Minimum surface for an inline-trigger plugin:

```ts
import type { IntegrationPlugin, TagExecutionResult } from '../types'

export const myIntegrationPlugin: IntegrationPlugin = {
  id: 'my_integration',
  executeTag(command, args, _config): TagExecutionResult {
    // Synchronous. Decide pill text + sync flag + payload here.
    return {
      pillContent: `${command}: ${args.join(' ')}`,
      syncWithTts: true,                          // see "syncWithTts decision" below
      effectPayload: { command, args },           // free shape; consumers read this
      sideEffect: undefined,                      // optional async work; fire-and-forget
    }
  },
}
```

Drop the file under `frontend/src/features/integrations/plugins/my_integration/` and wire the export through `registry.ts` the way Lovense does.

### 3. Consumer: subscribe to the bus

Wherever the effect is rendered (a global overlay, a per-message ornament, a hardware bridge, …):

```ts
import { eventBus } from '@/core/websocket/eventBus'
import { Topics } from '@/core/types/events'

useEffect(() => {
  return eventBus.on(Topics.INTEGRATION_INLINE_TRIGGER, (event) => {
    const trigger = event.payload as IntegrationInlineTrigger
    if (trigger.integration_id !== 'my_integration') return
    // Read trigger.command, trigger.args, trigger.payload, trigger.source
    // Render the effect, fire the hardware, update a store, ...
  })
}, [])
```

`trigger.source` is one of `'live_stream' | 'text_only' | 'read_aloud'` — useful when re-trigger should behave differently from the original (e.g. shorter duration on read-aloud).

### 4. System prompt: teach the model the tag

Define `MY_PROMPT_BLOCK` somewhere reachable by the registry (often a sibling `_my_integration_prompt.py`). XML wrapping is the convention used by every other integration:

```python
MY_PROMPT_BLOCK = '''<myintegration priority="normal">
You may emit visual effects inline using the markup:

  <my_integration shower 💖🔥🤘>
  <my_integration spotlight north>

Place these naturally inline with your prose. They are silent — the user
sees a small pill in chat where the tag appeared. Do not over-use them.
</myintegration>'''
```

Keep it short. The prompt assembler injects this verbatim alongside other active integration prompts; long extensions are expensive at every turn.

---

## syncWithTts decision

| Effect type | `syncWithTts` |
|---|---|
| Visual flourish that should land **with the spoken word** (emoji shower, screen flash, character expression) | `true` |
| Hardware that should react as soon as the model decides (Lovense vibrate, smart-light pulse) | `false` |
| Status updates / inline labels that don't really synchronise with anything | `false` |

`true` defers emission to `audioPlayback.onSegmentStart` of the segment that contains the tag. In `text_only` streams (no TTS pipeline) the buffer falls back to immediate emission regardless of the flag — the persona "speaks that fast".

---

## Side effects

`sideEffect: () => Promise<void>` runs fire-and-forget — `ResponseTagBuffer` does not await it; rejection is logged with `integration_id`, `command`, `args`, `effectId` for grep-ability. Use it for:

- Async I/O the plugin must perform (HTTP call to a local service, like Lovense's toy API)
- Anything that the pill rendering must NOT wait on

Do **not** use it for state mutations the bus consumer would do anyway — keep `sideEffect` for plugin-specific I/O, let the bus do the dispatching.

**Crucial:** at persisted-message render time (page reload, scroll-back), `runSideEffects: false` is set on the buffer, so your `sideEffect` thunks are silently skipped. Pill content and `effectPayload` are still computed identically — re-render must be idempotent. If your plugin's effect *cannot* survive being silently skipped on reload, that's a sign it should be running on the **bus subscriber** side, not in `sideEffect`.

---

## Persisted vs live: the equivalence invariant

The same input MUST produce the same `pillContent` whether the message is live-streaming or being re-rendered from history. The buffer's `executeTag` is called identically on both paths. Make sure your function is deterministic over `(command, args, config)` — no `Date.now()`, no `Math.random()` in `pillContent` (it's fine in `effectPayload` if consumers only care during live emit). The regression test at `frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts` locks this in.

---

## Common gotchas

- **Tag format is space-separated, no quotes.** `<my_integration shower 💖>` works; `<my_integration shower "💖">` produces `args = ['"💖"']` — the quotes are part of the arg.
- **Tags split across stream chunks are handled by the buffer.** You don't need to worry about partial reads.
- **Unknown commands**: return a non-failing result with an explanatory `pillContent` like `Lovense: unknown action "xyz"`. Don't throw — the buffer's error pill is for sync exceptions only.
- **Don't import `_internal` files of other modules.** `IntegrationDefinition` is the public surface; everything else lives behind the module's `__init__.py`.
- **British English** in code, comments, prompt strings, commit messages.

---

## Reference reading

- Spec: `devdocs/specs/2026-04-30-integration-inline-triggers-design.md`
- Lovense plugin (canonical): `frontend/src/features/integrations/plugins/lovense/`
- Buffer + sync/deferred logic: `frontend/src/features/integrations/responseTagProcessor.ts`
- Renderer pipeline: `frontend/src/features/chat/rehypeIntegrationPills.ts`
- Audio sync: `frontend/src/features/voice/pipeline/audioParser.ts` + `infrastructure/audioPlayback.ts`
- Bus envelope helper: `frontend/src/features/integrations/inlineTriggerBus.ts`
- Backend extension gate: `backend/modules/chat/_prompt_assembler.py` (heuristic) and `backend/modules/integrations/__init__.py` (`get_integration_prompt_extensions`)
