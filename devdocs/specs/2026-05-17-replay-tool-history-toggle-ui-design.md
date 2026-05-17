# `replay_tool_history` Cockpit Toggle UI — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** Follow-up to [reasoning + tool replay spec §6.2](2026-05-17-reasoning-tool-replay-design.md). UX decided in-session 2026-05-17 with Chris.
**Scope:** Add a user-facing toggle for `extras.replay_tool_history` to the chat cockpit. Desktop: separate button next to tools. Mobile: nested in the 🔧 group dropdown, with an "R" badge on the parent button when the flag is on.
**Depends on:** [`2026-05-17-replay-tool-history-per-turn-flag-design.md`](2026-05-17-replay-tool-history-per-turn-flag-design.md) being implemented first so the toggle's semantic is "applies to next turn".

---

## 1. UX overview

Two presentations, one underlying state (`extras.replay_tool_history`).

### 1.1 Desktop

A new `ReplayHistoryToggleButton` inside the `ReasoningToolsCluster`,
positioned immediately to the right of the existing `ToolsButton`. Same
shape, same accent. Icon: ↻ (or another circular-arrow glyph). Tooltip
text: "When on, past tool calls are re-injected into the model's context
on the next turn. Default: on."

Below the button (or in the tooltip — see §3.4): mini-hint **"Wirkt sich
ab der nächsten Antwort aus"** that appears for ~3 seconds after the user
clicks the toggle. After the timeout, the hint fades. Communicates the
non-retroactive semantics without permanent clutter.

### 1.2 Mobile

The replay-history toggle joins the dropdown menu of the existing 4th
button from left — the `CockpitGroupButton` with `icon="🔧"` that
already contains `ImageButton` + `IntegrationsButton`. The new toggle
sits as the **last** entry in that menu.

When `extras.replay_tool_history === true` (the default), the parent
🔧 button displays a small **"R"** badge in its bottom-left corner.
When `false`, no badge.

Chris's rationale for variant A (badge on default, not on
non-default): the feature is a positive capability, permanent visibility
adds awareness without harm.

The mini-hint "Wirkt sich ab der nächsten Antwort aus" appears under
the toggle inside the dropdown menu for ~3 seconds after a state change.

---

## 2. Component design

### 2.1 New file — `ReplayHistoryToggleButton.tsx`

Path: `frontend/src/features/chat/cockpit/buttons/ReplayHistoryToggleButton.tsx`.

Shape mirrors `ThinkingButton.tsx`:

```tsx
import { CockpitButton } from '../CockpitButton'
import { useCockpitStore } from '../cockpitStore'

interface Props { sessionId: string }

export function ReplayHistoryToggleButton({ sessionId }: Props) {
  const extras = useCockpitStore((s) => s.entries[sessionId]?.extras)
  const enabled = extras?.replay_tool_history ?? true
  const onClick = () => {
    useCockpitStore.getState().patchExtras(sessionId, {
      replay_tool_history: !enabled,
    })
  }
  return (
    <CockpitButton
      icon="↻"
      state={enabled ? 'active' : 'idle'}
      accent="neutral"
      label={`Tool history replay: ${enabled ? 'on' : 'off'}`}
      tooltip="When on, past tool calls are re-injected into the model's context on the next turn. Default: on."
      onClick={onClick}
    />
  )
}
```

ARIA `label` reflects state for screen readers.

### 2.2 Bottom-left badge prop on `CockpitGroupButton`

Path: `frontend/src/features/chat/cockpit/CockpitGroupButton.tsx`.

Add an optional prop `bottomLeftBadge?: string | null`. Renders a
small dotted/rounded chip with the given text in the bottom-left
corner. `aria-hidden="true"` — already conveyed by the menu's open
state.

CSS specifics:
- Position: `absolute; bottom: 4px; left: 4px;`
- Background: subtle accent (match existing badge colours in
  `frontend/src/features/chat/cockpit/CockpitButton.tsx`)
- Min-size 16px, line-height 1, font-size 10px
- Pointer-events: none — the badge does not interfere with the
  button's hit-target.

### 2.3 CockpitBar wiring

Path: `frontend/src/features/chat/cockpit/CockpitBar.tsx`.

**Desktop branch (`!isMobile`):**
Add `<ReplayHistoryToggleButton sessionId={props.sessionId} />` inside
the `ReasoningToolsCluster` directly after `ToolsButton`. If the cluster
component owns its own layout, lift the new button as a sibling next
to it, separated by a `<Sep />`.

**Mobile branch (`isMobile`):**
Add the new button as the last child of the existing
`<CockpitGroupButton icon="🔧">`:

```tsx
const toolsGroupChildren = (
  <>
    <ImageButton sessionId={props.sessionId} onOpenLlmProviders={openLlmProviders} />
    <IntegrationsButton activePersonaIntegrationIds={props.activePersonaIntegrationIds} />
    <ReplayHistoryToggleButton sessionId={props.sessionId} />
  </>
)
```

And pass the badge:

```tsx
const replayActive = Boolean(cockpit?.extras?.replay_tool_history ?? true)

<CockpitGroupButton
  icon="🔧"
  label="Image and integrations"
  hasActiveChild={toolsActive}
  bottomLeftBadge={replayActive ? 'R' : null}
>
  {toolsGroupChildren}
</CockpitGroupButton>
```

### 2.4 Mini-hint plumbing

Two display contexts:

**Desktop**: a transient hint label next to or below the new button.
Simplest approach: a local `useState` on the toggle component plus a
`setTimeout` to clear it after 3000ms. Hint content lives inside the
button's container.

**Mobile**: the hint shows inside the dropdown menu, near the new
toggle, also for ~3000ms after a state change. Same local-state
pattern. The dropdown menu's collapse on user re-click is unrelated.

In both contexts the hint reads:
> "Wirkt sich ab der nächsten Antwort aus" *(or English equivalent
> "Applies from the next response" per the locale fixture if i18n is
> in play; check `frontend/src/i18n/` for the convention).*

---

## 3. Persistence

`extras.replay_tool_history` is already part of `ChatSessionExtras`
(backend + DTO from the earlier reasoning + tool replay spec). The
toggle's `patchExtras` call hits the same endpoint that
`extras.tools_enabled` / `extras.reasoning_mode` use. No new endpoint,
no new event topic, no new persistence code.

Cross-tab synchronisation already works via the existing
`chat.session.extras.updated` event handled by `cockpitStore`.

---

## 4. Tests

### 4.1 Unit — `ReplayHistoryToggleButton.test.tsx`

`frontend/src/features/chat/cockpit/buttons/__tests__/ReplayHistoryToggleButton.test.tsx`:

- Renders with `state="active"` when `extras.replay_tool_history === true`.
- Renders with `state="idle"` when `false`.
- Click calls `patchExtras` with the negated value.
- Re-renders state on `cockpit.extras.updated` event.

### 4.2 Cockpit bar — `CockpitBar.test.tsx` (extend)

- Desktop: new button appears in the cluster after ToolsButton.
- Mobile: new button is the last child of the 🔧 CockpitGroupButton's
  expanded content.
- Mobile: R-badge on 🔧 button visible when `replay_tool_history === true`
  (default), absent when `false`.

### 4.3 Mini-hint timing — light test

Render the button, click, assert the hint appears. Wait 3000ms, assert
the hint is gone. Use `vi.useFakeTimers()` to avoid actual waits.

---

## 5. Accessibility

- Button: `aria-label="Tool history replay: on"` / `"off"`.
- Badge: decorative, `aria-hidden="true"`.
- Hint: not a critical accessibility surface; the tooltip on the
  button is the canonical explanation for AT users.
- Keyboard: existing cockpit button focus handling covers it.
- Reduced motion: hint fade respects `prefers-reduced-motion: reduce`
  by skipping the fade transition (instant appear / disappear).

---

## 6. Backwards compatibility

- Additive UI. Existing buttons unchanged.
- `extras.replay_tool_history` defaults to `true` everywhere; users
  see the new button in its "active" state immediately, with the R
  badge on mobile, behaviour unchanged from yesterday.
- If the per-turn flag spec
  (`replay-tool-history-per-turn-flag-design.md`) has shipped before
  this toggle, the user gets the stable "applies from next response"
  semantic, which the mini-hint communicates.

---

## 7. Implementation order

1. `CockpitGroupButton` gains the `bottomLeftBadge` prop.
2. New `ReplayHistoryToggleButton.tsx`.
3. `CockpitBar.tsx` wiring (desktop + mobile, with the badge derived
   from `extras.replay_tool_history`).
4. Mini-hint state + timeout on `ReplayHistoryToggleButton`.
5. Tests per §4.
6. INSIGHTS.md entry (next free INS number after the per-turn-flag spec).
7. `pnpm tsc --noEmit` clean; `pnpm test` clean.

---

## 8. What this unblocks

- Branching: each branch carries its own `extras.replay_tool_history`
  in the cloned session document; user can toggle per branch
  independently. The R-badge surfaces the branch's current state at
  a glance.
- Users can experiment with how the model behaves with and without
  prior tool replay — useful for cost tuning on tool-heavy sessions.
