# Screen Effects Integration — Design

**Status:** Draft, ready for plan
**Author:** Chris (with Claude)
**Date:** 2026-04-30
**Related:** `devdocs/specs/2026-04-30-integration-inline-triggers-design.md` (foundation), `devdocs/plugin-author-inline-triggers.md` (cookbook)

---

## 1. Motivation

Chatsune already has a foundation for inline-trigger integrations: an LLM-emitted tag that the frontend recognises, parses, and dispatches as both an inline pill and a typed bus event. The canonical example today is Lovense (hardware actions). What is missing is a **purely visual** integration that demonstrates the same primitive without external hardware — and gives Chatsune a fun, low-stakes ambient layer that users encounter on day one.

`screen_effect` is that integration. It is enabled by default for every user, ships with one initial effect (`rising_emojis`), and is structured so that further effects (background animations like a beating heart or lightning, viewport shake, …) can be added without restructuring the plugin.

**Why an inline-trigger integration and not a tool?**
- Tools are not always available — voice-only chats, restricted models, or persona-level tool gating may deny them. Inline tags are cheap text and travel through every model.
- Inline tags carry **timing**: when the integration's `syncWithTts` is true, the frontend defers the bus emission until the surrounding sentence reaches TTS playback. The visual flourish lands with the spoken word, not before.

---

## 2. Goals & non-goals

### Goals
- Add a registered integration `screen_effect` (singular) with display name "Screen Effects".
- Default-on for every user, opt-out via the user-level Integrations tab.
- Initial effect `rising_emojis` — a brief, gentle upward shower of 1-5 emojis varying in size, drift, rotation, and timing.
- Synchronise with TTS when active; immediate emit in text-only streams.
- Re-trigger the full effect on user-initiated read-aloud of older messages.
- Respect `prefers-reduced-motion` with a markedly softer profile (no opt-out from the effect — the pill stays — but the visual gets calm).
- Round-trip equivalence: a re-rendered persisted message produces the same pill as the live render.
- Architecturally extensible: adding a second effect (e.g. `beating_heart`) means dropping one more file in `effects/` and one more component in `overlay/`.

### Non-goals
- Multiple simultaneous-effect coordination (cancellation, queueing, merging). Parallel tags overlap and finish on their own.
- Per-persona configuration. The integration is global per user.
- Effect telemetry, analytics, A/B variants.
- Animation snapshot testing. DOM-randomised motion is not snapshot-friendly; manual verification covers it.

---

## 3. Architecture overview

```
backend/modules/integrations/
  _registry.py                           ← +1 register(...) call for screen_effect
  _screen_effects_prompt.py              ← NEW: SCREEN_EFFECT_PROMPT constant

frontend/src/features/integrations/plugins/screen_effects/
  index.ts                               ← NEW: registerPlugin
  tags.ts                                ← NEW: executeTag dispatcher (Map command → effect fn)
  effects/
    risingEmojis.ts                      ← NEW: parsing + payload + pill builder
  overlay/
    ScreenEffectsOverlay.tsx             ← NEW: global mount, bus subscriber, dispatcher
    RisingEmojisEffect.tsx               ← NEW: particle animation component
```

**Mount point:** `<ScreenEffectsOverlay />` is rendered once near the App root (sibling to `<Routes>`). Container is `position: fixed; inset: 0; pointer-events: none; overflow: hidden; z-index: 90`. It sits above ordinary chat UI but below modals and toasts.

**Data flow** (existing infrastructure unless marked NEW):

```
LLM stream
  → ResponseTagBuffer detects <screen_effect ...>
  → screen_effects/tags.ts::executeTag (NEW) parses command + args, distinct-graphemes, builds pill
  → TagExecutionResult { pillContent, syncWithTts: true, effectPayload, sideEffect: undefined }
  → rehypeIntegrationPills renders the inline pill
  → Bus emits Topics.INTEGRATION_INLINE_TRIGGER
       (deferred to audioPlayback.onSegmentStart when TTS active; immediate in text_only)
  → ScreenEffectsOverlay (NEW, subscriber) filters integration_id, dispatches by payload.effect
  → RisingEmojisEffect (NEW) spawns DOM emoji spans over the viewport
```

---

## 4. Backend — `IntegrationDefinition`

`backend/modules/integrations/_registry.py` (inside `_register_builtins()`):

```python
register(IntegrationDefinition(
    id="screen_effect",
    display_name="Screen Effects",
    description="Visual inline flourishes the persona drops over the screen.",
    icon="sparkles",
    execution_mode="frontend",
    config_fields=[],
    capabilities=[],
    system_prompt_template=SCREEN_EFFECT_PROMPT,
    response_tag_prefix="screen_effect",   # MUST equal id
    tool_definitions=[],
    default_enabled=True,
    assignable=False,
))
```

The `icon` field is a backend metadata slug only — at the time of writing, the frontend `IntegrationsTab` does not render integration icons (it relies on `display_name`), so no SVG asset is required. If a future tab adds icon rendering, `sparkles` is a sensible default; otherwise the slug just travels with the definition for completeness.

### Prompt block

`backend/modules/integrations/_screen_effects_prompt.py`:

```python
SCREEN_EFFECT_PROMPT = '''<screeneffects priority="normal">
You may emit small visual flourishes inline using the markup:

  <screen_effect rising_emojis 💖 🤘 🔥>

Available effects:
  - rising_emojis EMOJI [EMOJI ...] — a gentle upward shower of the given
    emojis (1..5), drifting and varying in size. Pass between 1 and 5
    distinct emojis.

Use sparingly — once per response at most, and only when it genuinely fits
the moment (a celebration, a flirt, a punchline). The user sees a small
monospace pill in chat at the spot where the tag appeared, and the effect
plays over the whole screen briefly. Effects are silent and never carry
prose meaning — your words still need to do the talking.
</screeneffects>'''
```

**Notes:**
- Singular tag form (`<screen_effect ...>`), plural display name. Prefix === id is enforced by the foundation.
- "1..5" cap surfaces both as a soft hint to the model and a hard limit in the parser.
- "use sparingly" / "never carry prose meaning" guards against the LLM turning chat into an emoji circus or substituting effects for words.

The existing prompt-assembler heuristic (`backend/modules/chat/_prompt_assembler.py`) injects `system_prompt_template` regardless of `tools_enabled` because there are no tools — exactly what we want here.

---

## 5. Frontend plugin

### `tags.ts` — dispatcher

```typescript
import type { TagExecutionResult } from '../../types'
import { risingEmojis } from './effects/risingEmojis'

type EffectFn = (args: string[]) => TagExecutionResult

const EFFECTS: Record<string, EffectFn> = {
  rising_emojis: risingEmojis,
}

export function executeTag(
  command: string,
  args: string[],
  _config: Record<string, unknown>,
): TagExecutionResult {
  const fn = EFFECTS[command.toLowerCase()]
  if (!fn) {
    return {
      pillContent: `screen_effect: unknown "${command}"`,
      syncWithTts: true,
      effectPayload: { error: 'unknown_effect', command },
    }
  }
  return fn(args)
}
```

### `effects/risingEmojis.ts`

```typescript
import type { TagExecutionResult } from '../../../types'

const MAX_EMOJIS = 5
const FALLBACK_EMOJI = '✨'

export function risingEmojis(args: string[]): TagExecutionResult {
  const emojis = parseEmojis(args)
  if (emojis.length === 0) {
    return {
      pillContent: '✨ rising_emojis (no emojis)',
      syncWithTts: true,
      effectPayload: { effect: 'rising_emojis', emojis: [FALLBACK_EMOJI] },
    }
  }
  return {
    pillContent: `✨ rising_emojis ${emojis.join('')}`,
    syncWithTts: true,
    effectPayload: { effect: 'rising_emojis', emojis },
  }
}

function parseEmojis(args: string[]): string[] {
  const seg = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  const out: string[] = []
  const seen = new Set<string>()
  for (const arg of args) {
    for (const { segment } of seg.segment(arg)) {
      const trimmed = segment.trim()
      if (!trimmed) continue
      if (seen.has(trimmed)) continue
      seen.add(trimmed)
      out.push(trimmed)
      if (out.length >= MAX_EMOJIS) return out
    }
  }
  return out
}
```

**Why these choices:**
- `Intl.Segmenter` with `granularity: 'grapheme'` keeps ZWJ-sequences (`👨‍👩‍👧`) and skin-tone modifiers (`👋🏽`) intact — naive `Array.from(string)` would split them.
- `seen` Set spans all args → distinct works whether the LLM writes `💖 💖 🔥`, `💖🔥 💖`, or `💖🔥` plus a duplicate later.
- `out.length >= MAX_EMOJIS` enforces the cap deterministically — no UB on overflow.
- Empty-list fallback returns a defensive payload so the overlay never receives zero emojis.

### `index.ts` — plugin registration

```typescript
import type { IntegrationPlugin } from '../../types'
import { registerPlugin } from '../../registry'
import { executeTag } from './tags'

const screenEffectsPlugin: IntegrationPlugin = {
  id: 'screen_effect',
  executeTag,
}

registerPlugin(screenEffectsPlugin)

export default screenEffectsPlugin
```

No `executeTool`, no `healthCheck`, no `emergencyStop`, no `ConfigComponent` — this plugin owns nothing user-configurable. The whole user surface is one toggle in the Integrations tab (handled by existing infrastructure via `default_enabled` + per-user override).

---

## 6. Render layer

### `ScreenEffectsOverlay.tsx`

```tsx
import { useEffect, useState } from 'react'
import { eventBus } from '@/core/websocket/eventBus'
import { Topics } from '@/core/types/events'
import type { IntegrationInlineTrigger } from '@/features/integrations/inlineTriggerBus'
import { RisingEmojisEffect } from './RisingEmojisEffect'

type ActiveEffect = {
  id: string
  kind: 'rising_emojis'
  emojis: string[]
  reduced: boolean
}

export function ScreenEffectsOverlay() {
  const [active, setActive] = useState<ActiveEffect[]>([])

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    return eventBus.on(Topics.INTEGRATION_INLINE_TRIGGER, (event) => {
      const trigger = event.payload as IntegrationInlineTrigger
      if (trigger.integration_id !== 'screen_effect') return
      const payload = trigger.payload as { effect?: string; emojis?: string[] }
      if (payload.effect !== 'rising_emojis') return
      const id = trigger.effectId ?? crypto.randomUUID()
      setActive((prev) => [
        ...prev,
        {
          id,
          kind: 'rising_emojis',
          emojis: payload.emojis ?? ['✨'],
          reduced,
        },
      ])
    })
  }, [])

  const remove = (id: string) =>
    setActive((prev) => prev.filter((e) => e.id !== id))

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 90,
        overflow: 'hidden',
      }}
      aria-hidden="true"
    >
      {active.map((e) =>
        e.kind === 'rising_emojis' ? (
          <RisingEmojisEffect
            key={e.id}
            emojis={e.emojis}
            reduced={e.reduced}
            onDone={() => remove(e.id)}
          />
        ) : null,
      )}
    </div>
  )
}
```

### `RisingEmojisEffect.tsx`

The "Subtil" preset validated in the brainstorming companion:

```ts
const PROFILE_FULL = {
  count: 14,
  spawnMs: 1400,
  sizeMin: 22,
  sizeMax: 38,
  drift: 30,        // ±30px horizontal drift
  riseMs: 2200,
}

const PROFILE_REDUCED = {
  count: 4,
  spawnMs: 1200,
  sizeMin: 22,
  sizeMax: 30,
  drift: 12,
  riseMs: 2600,
}
```

Implementation outline:

- On mount, pick `PROFILE_REDUCED` if `reduced` else `PROFILE_FULL`.
- Schedule `count` particles distributed over `spawnMs` (uniform with small jitter).
- Each particle is a `<span>` appended to a child container, with per-element randomised:
  - Emoji: `emojis[Math.floor(Math.random() * emojis.length)]` (uniform pick)
  - Horizontal start position: `random * containerWidth - margin`
  - Size: `sizeMin + random * (sizeMax - sizeMin)`
  - Drift: `(random - 0.5) * drift * 2`
  - Rotation start/end: small random
  - Animation duration: `riseMs + (random - 0.5) * 600`
  - Spawn delay
- CSS keyframe `emojiRise` translates from `0,0` to `(drift, -(viewportHeight + size + 30))`, with opacity fade-in (10%) and fade-out (85% → 100%), scale `0.6 → 1 → 0.9`.
- Each `<span>` self-removes via `animationend` listener.
- After `spawnMs + max(riseMs) + 300ms` safety margin, parent calls `onDone` so the entry leaves `active`.

Random parameters live entirely in the component, never in `executeTag` — preserves the live-vs-persisted equivalence invariant.

### Mount

In `frontend/src/App.tsx`, inside `AppRoutes`, render the overlay as a sibling to `<Routes>` and `<LastRouteTracker />`:

```tsx
return (
  <>
    <LastRouteTracker />
    <Routes>{/* ... */}</Routes>
    <ScreenEffectsOverlay />
  </>
)
```

It must render once globally, not per-route, so an effect started during chat continues if the user navigates away. It does not need to be inside `AuthGuard` — an emoji storm on the login screen would be harmless, and gating it on auth would only matter if we later persist effect state, which we explicitly do not.

Side-effect import (matching the existing Lovense pattern at `App.tsx:11-13`):

```tsx
import './features/integrations/plugins/screen_effects'
```

Add this import alongside the other plugin imports so the plugin self-registers at module load.

---

## 7. Behaviour matrix

| Situation | Behaviour |
|---|---|
| **Live stream, TTS active** | `executeTag` runs immediately on tag detection (pill renders); bus emit deferred to `audioPlayback.onSegmentStart` of the segment containing the tag — animation lands with the spoken word. |
| **Live stream, text-only** | `executeTag` runs, pill renders, bus event emits **immediately** (buffer fallback) — animation starts at once. |
| **History re-render** (page reload, scrollback) | Buffer runs with `runSideEffects: false`. Pill is recomputed identically (deterministic `executeTag`); no bus event, **no animation**. Pill remains as a marker. |
| **`read_aloud`** (user clicks "speak this" on an old message) | Buffer runs with `runSideEffects: true` and `source: 'read_aloud'`. Pill renders, bus event emits in sync with TTS, animation plays at full intensity. Read-aloud is a user-triggered experience replay. |
| **`prefers-reduced-motion: reduce`** | Subscriber reads the media query at mount, passes `reduced` flag to the effect component → `PROFILE_REDUCED` instead of `PROFILE_FULL`. Pill is unchanged. |
| **Integration disabled by user** | Backend does not inject the prompt block (existing prompt-assembler logic), so the LLM has no markup to emit. If a tag somehow leaks through, `executeTag` still runs and renders the pill, but the bus event is the trigger for animation; without an active subscriber path the user sees just the pill. |
| **Unknown effect** (`<screen_effect cartwheel>`) | `executeTag` returns an "unknown" pill (`screen_effect: unknown "cartwheel"`), payload has no valid `effect` field → overlay ignores. No crash, visible hint. |
| **Zero emojis** (`<screen_effect rising_emojis>`) | `parseEmojis` returns `[]`, fallback pill `✨ rising_emojis (no emojis)`, payload carries `emojis: ['✨']` so the storm plays with sparkles. |
| **Excess emojis** (`<screen_effect rising_emojis 1 2 3 4 5 6 7>`) | Parser caps at 5; remaining args are silently dropped. |
| **Multiple `<screen_effect>` tags in one response** | Each tag spawns its own entry in `active`. Storms overlap, each finishes independently via its own `onDone`. No cancellation or queue. |

---

## 8. Equivalence invariant

The same input MUST produce the same `pillContent` whether live-streaming or re-rendering from history. `executeTag` and `parseEmojis` are deterministic over `(command, args, config)`:

- No `Math.random` in pill construction.
- No `Date.now` in pill construction.
- Random-only fields (`sizeMin..sizeMax` rolls, drift rolls, …) live in `RisingEmojisEffect.tsx`, not in the plugin.

The existing regression test `frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts` extends with `screen_effect` cases.

---

## 9. Testing

### Automated (Vitest)

`frontend/src/features/integrations/plugins/screen_effects/__tests__/parseEmojis.test.ts`:

- `parseEmojis(['💖', '🤘', '🔥'])` → `['💖', '🤘', '🔥']`
- `parseEmojis(['💖🤘🔥'])` → `['💖', '🤘', '🔥']` (concatenated split)
- `parseEmojis(['💖', '💖🤘'])` → `['💖', '🤘']` (distinct over args)
- `parseEmojis(['👨‍👩‍👧'])` → `['👨‍👩‍👧']` (ZWJ intact)
- `parseEmojis(['👋🏽'])` → `['👋🏽']` (skin-tone modifier intact)
- `parseEmojis([])` → `[]`
- `parseEmojis(['💖🤘🔥💪🎉🌈'])` → 5 elements (cap at MAX_EMOJIS)
- `parseEmojis(['  💖  '])` → `['💖']` (whitespace ignored)

`frontend/src/features/integrations/plugins/screen_effects/__tests__/executeTag.test.ts`:

- `rising_emojis` with valid args → `pillContent` matches `^✨ rising_emojis `, `syncWithTts: true`, `effectPayload.effect === 'rising_emojis'`
- Unknown command → pill matches `^screen_effect: unknown`, payload has `error: 'unknown_effect'`
- `rising_emojis` with empty args → fallback pill, `effectPayload.emojis === ['✨']`
- Case-insensitive command (`Rising_Emojis`) → still dispatched to `rising_emojis`

`frontend/src/features/chat/__tests__/livePersistedPillEquivalence.test.ts` (extend existing):

- Live and persisted paths render identical pill HTML for `<screen_effect rising_emojis 💖 🤘 🔥>`

### Backend (pytest, if a registry test exists today)

- `get('screen_effect')` returns a definition with `default_enabled=True`, `assignable=False`, `response_tag_prefix == "screen_effect"`, non-empty `system_prompt_template`.

### No animation snapshot

DOM-randomised motion is not snapshot-friendly. `RisingEmojisEffect` gets only a smoke-mount test (mounts without crash for varied `emojis` arrays, including length-1 and length-5).

---

## 10. Manual verification

Run all of these on a real device after implementation. Tick each off in the PR description.

1. **Default-on after migration.** A user account without an explicit `screen_effect` config doc has the integration active. Verify in `/admin` or by inspecting the integrations API directly.
2. **Live stream + TTS.** With xAI Voice (or Mistral Voice) active, prompt the LLM to celebrate. The emoji storm starts when the relevant word is spoken, not before.
3. **Live stream + text-only.** TTS off, same prompt. Storm starts immediately when the tag streams in.
4. **History re-render.** After a successful storm, full page reload. The pill remains visible. **No** storm replays.
5. **Read-aloud.** On the same persisted message, trigger "read aloud" via the UI. Storm plays at full intensity again.
6. **User toggle off.** In the Integrations tab, disable Screen Effects. New chat turn → no `<screen_effect>` tag in LLM output (prompt block not injected), no storm.
7. **`prefers-reduced-motion`.** Enable "Reduce motion" at the OS level (Hyprland: GTK setting; macOS / iOS: Accessibility). Trigger the effect. The storm is visibly calmer (4 emojis, gentler drift).
8. **Compound emojis.** Manually emit `<screen_effect rising_emojis 👨‍👩‍👧 🌈>` (e.g. via the LLM harness or backend dev poke). Both render correctly, no broken glyphs.
9. **Mobile** (under `lg` breakpoint, on a real phone or sized browser). Storm renders correctly above the mobile drawer, no layout interference.
10. **Parallel tags.** Provoke the LLM into emitting two `<screen_effect rising_emojis ...>` tags in one answer. Both storms play simultaneously; both pills appear in the message body.

---

## 11. Future effects (informational, not part of this work)

The architecture leaves room for these without changes to the dispatcher contract:

- **`beating_heart`** — semi-transparent SVG heart pulses 3× over the chat stream (background-effect, not particle).
- **`lightning`** — flash + thunder background overlay.
- **`screen_shake`** — short viewport shake (CSS transform on a wrapping container).

Each future effect adds:

- One file under `effects/` (parsing + payload + pill builder).
- One entry in `EFFECTS` in `tags.ts`.
- One component under `overlay/`.
- One discriminant case in `ActiveEffect` and one rendering branch in `ScreenEffectsOverlay`.
- One bullet in the prompt block.

Deferred until `rising_emojis` ships and gets feedback in real use.

---

## 12. Migration considerations

`default_enabled=True` plus `assignable=False` means existing users automatically have the integration active without any database mutation: the resolver in the integrations module treats absence of a per-user config doc as "use the default". No migration script needed, in line with the project's "no more wipes" rule (CLAUDE.md, "Data Model Migrations"). Users who previously stored an explicit "off" toggle for any other integration are unaffected — they have no `screen_effect` doc, and the default resolves to enabled. Users can opt out post-rollout via the existing user-level Integrations tab toggle.

---

## 13. Out-of-scope reminders

- No persistence of effect history.
- No analytics or telemetry.
- No per-persona toggle.
- No theming hooks (effect parameters are hard-coded constants for now).
- No animation snapshot tests.
- No backend tracking of which effects fired — events are fully ephemeral.
