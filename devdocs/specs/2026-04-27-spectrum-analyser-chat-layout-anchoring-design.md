# Spectrum Analyser — Chat-Layout Anchoring

**Date:** 2026-04-27
**Status:** Spec
**Component:** `frontend/src/features/voice/components/VoiceVisualiser.tsx` (and renderers)

## Problem

The voice visualiser canvas is a fullscreen fixed overlay. Its bar field is
clamped to a hard-coded 90% of the **viewport** width (`WIDTH_FRACTION = 0.9`
in `visualiserRenderers.ts`). This has two visible faults:

1. On desktop with the sidebar visible, the bars run over the sidebar
   because the renderer has no notion of the sidebar's existence.
2. The width is anchored to the viewport, not to the chat content. On wide
   screens the bars drift far away from the centred message column they
   are supposed to react to.

The intended behaviour is for the bars to belong visually to the chat
view: anchored to the centred text column on desktop, filling the
available width on mobile, and never spilling onto the sidebar.

## Goals

- Anchor the bar field horizontally to the chat layout, not the viewport
- Maintain a small overhang past the text column on wide screens so the
  bars feel airy rather than crammed into the message column
- Smoothly transition between the wide-desktop and narrow-mobile layouts
  with no breakpoint-style jumps
- Suppress the visualiser on routes where there is no chat (e.g. admin,
  settings)

## Non-Goals

- Changing the visualiser's vertical layout (canvas stays fullscreen, bars
  stay vertically centred — out of scope)
- Animating the width transition when the sidebar toggles (a single-frame
  jump is acceptable; revisit only if it looks bad in practice)
- Changing any visualiser style (sharp / soft / glow / glass) — all four
  consume `barLayout` and benefit automatically
- Adding any new user-facing setting for the layout

## Design

### Width Algorithm

Two reference widths drive the layout:

- `textColumn` — the `mx-auto max-w-3xl` container in `MessageList.tsx:132`
  that holds the messages (max 768px / 48rem)
- `chatview` — the area bounded by the inner sides of the sidebar(s),
  i.e. the wrapper of the chat route's content excluding the sidebar

Bar-field width is computed as:

```
target     = textColumn.w * 1.2
usable     = min(target, chatview.w)
centre     = textColumn.x + textColumn.w / 2
left       = max(chatview.x,                  centre - usable / 2)
right      = min(chatview.x + chatview.w,     centre + usable / 2)
finalWidth = right - left
xOffset    = left
```

Both `left` and `right` are clamped to the chat view's bounds, so the
bars can never enter the sidebar region even if the text column sits
off-centre relative to the chat view (it does not in practice — the
column is `mx-auto` — but the clamp is robust).

When `chatview.w >> textColumn.w` (wide desktop), `usable` resolves to
`1.2 * textColumn.w` ⇒ the bars overhang the text column by 10% on each
side.

When `chatview.w == textColumn.w` (narrow), `usable` resolves to
`chatview.w` ⇒ the bars fill the chat view edge-to-edge.

In between (`textColumn.w < chatview.w < 1.2 * textColumn.w`), `usable`
shrinks smoothly from `1.2 * textColumn.w` down to `chatview.w` — no
jumps.

When the chat view is **narrower** than the text column (which only
happens transiently during resize, since the column has `max-w-3xl` not
a fixed width), the renderer still degrades gracefully: `finalWidth`
clamps to `chatview.w`.

### Suppression Outside Chat

The visualiser is mounted at the `AppLayout` level and is therefore
present on every route. To suppress it on non-chat routes we use the
fact that the layout state is owned by `ChatView` / `MessageList`: when
the chat is not mounted, no component reports bounds, the store stays
in its `null` state, and the visualiser short-circuits its render path.
No router-level coupling.

### State Layer

A new Zustand store `visualiserLayoutStore`:

```ts
type Bounds = { x: number; w: number }  // viewport-relative CSS pixels

type LayoutState = {
  chatview: Bounds | null
  textColumn: Bounds | null
  setBounds: (target: 'chatview' | 'textColumn', b: Bounds | null) => void
}
```

This mirrors the existing `visualiserPauseStore` style and lives next to
it under `frontend/src/features/voice/stores/`.

### Reporting Hook

A new hook `useReportBounds(ref, target)`:

- Attaches a `ResizeObserver` to `ref.current`
- On every observation, writes `{ x, w }` (from `getBoundingClientRect`)
  into the store under `target`
- On unmount, sets the slot to `null`
- Also fires once on mount (some browsers don't fire `ResizeObserver` for
  the initial layout pass)

The hook lives at
`frontend/src/features/voice/infrastructure/useReportBounds.ts`.

Note: `getBoundingClientRect` returns viewport-relative coordinates,
which is what the renderer wants because the canvas is itself a fixed
overlay sized to the viewport — `xOffset` is then directly a canvas-pixel
offset (DPR is clamped to 1 in this canvas).

### Renderer Changes

`visualiserRenderers.ts`:

- Remove the `WIDTH_FRACTION = 0.9` constant
- `barLayout` signature changes from
  `barLayout(width, height, n, frac)` to
  `barLayout(width, height, n, frac, geometry)` where:
  ```ts
  type Geometry = {
    chatview: Bounds      // not nullable here — caller must short-circuit
    textColumn: Bounds
  }
  ```
- The `usableWidth` and `xOffset` are computed from the geometry per the
  width algorithm above
- All four draw functions (`drawSharp`, `drawSoft`, `drawGlow`,
  `drawGlass`) keep their bodies — they call the new `barLayout` and use
  the returned `xOffset` and `slot` exactly as before

### Visualiser Component Changes

`VoiceVisualiser.tsx`:

- Subscribe to `visualiserLayoutStore` via Zustand
- If `chatview === null` or `textColumn === null`:
  - Stop the RAF loop if it's running
  - Clear the canvas once
  - Return early on every subsequent tick until bounds reappear
- Otherwise: pass `{ chatview, textColumn }` through to
  `drawVisualiserFrame`

The store dependency is added to the existing `useEffect` deps array so
that the loop re-arms when bounds become available or disappear.

### Reporting Sites

Two ref attachments:

1. **`ChatView.tsx`** — a ref on the outermost wrapper of the chat
   layout (the element that occupies the area between the sidebar and
   the right edge). Hook: `useReportBounds(chatviewRef, 'chatview')`.
2. **`MessageList.tsx:132`** — a ref on the existing
   `mx-auto max-w-3xl flex-col gap-4` div. Hook:
   `useReportBounds(textColRef, 'textColumn')`.

The exact element chosen for `ChatView`'s ref is implementation-time —
the candidate is the outermost positioning wrapper inside the route's
component. What matters: it must reflect the inner-of-sidebars area,
i.e. `<main>` is a reasonable target if `ChatView` doesn't introduce its
own outer wrapper.

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/features/voice/stores/visualiserLayoutStore.ts` | **New** — Zustand store with `chatview`, `textColumn`, `setBounds` |
| `frontend/src/features/voice/infrastructure/useReportBounds.ts` | **New** — `ResizeObserver`-backed hook reporting into the store |
| `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` | **Modified** — `barLayout` takes geometry; `WIDTH_FRACTION` removed |
| `frontend/src/features/voice/components/VoiceVisualiser.tsx` | **Modified** — subscribes to store; short-circuits when bounds are null; passes geometry through |
| `frontend/src/features/chat/ChatView.tsx` | **Modified** — ref on outer wrapper, `useReportBounds(_, 'chatview')` |
| `frontend/src/features/chat/MessageList.tsx` | **Modified** — ref on `max-w-3xl` container, `useReportBounds(_, 'textColumn')` |
| `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts` | **Modified** — extended geometry test cases |

## Edge Cases

- **Window resize:** `ResizeObserver` fires → store updates → next RAF
  frame draws with new geometry. No explicit code.
- **Sidebar collapse / expand:** changes the chat view's width →
  observer fires on the chat view ref. Text column width is unchanged
  (still `max-w-3xl`), but its viewport `x` shifts when the chat view's
  origin shifts → observer fires on the text-column ref too.
- **Orientation change (mobile):** `ResizeObserver` fires for both
  refs, no special handling.
- **Mount order:** `VoiceVisualiser` mounts in `AppLayout` before
  `ChatView` mounts inside the route. Until `ChatView` reports, both
  store slots are `null` and the visualiser is inactive. The store
  subscription triggers the visualiser's effect to re-arm once bounds
  arrive.
- **Route change away from chat:** `ChatView` unmounts → hooks set both
  slots to `null` → visualiser short-circuits. Canvas is cleared.
- **Chat view momentarily narrower than text column:** during a resize
  drag the chat view can briefly be narrower than 768px while the text
  column is still measured at its previous (clamped) width. The
  algorithm clamps `right` at `chatview.x + chatview.w`, so
  `finalWidth` stays ≤ chat view width — no overflow.
- **Reduced motion:** unchanged. The RAF loop runs but skips drawing.
  Same behaviour as today.

## Manual Verification

Run the frontend (`pnpm dev`). Trigger TTS in a chat session for each
case:

1. **Desktop wide (≥ 1280px), sidebar visible:**
   bars centred over the message column, ~120% of column width, never
   overlapping the sidebar.
2. **Desktop wide, sidebar collapsed:**
   bars shift with the message column (column re-centres in the wider
   chat view), still ~120% of column width.
3. **Window narrowed to ~900px:**
   text column still clamps at 768px; bars still ~120% (still fits).
4. **Window narrowed to ~800px:**
   `1.2 × 768 = 921 > 800` ⇒ bars now equal chat view width, smoothly
   shrinking as you drag inward — no visible jump.
5. **Mobile width (< 768px):**
   text column shrinks to fit the chat view; bars fill the chat view
   edge-to-edge.
6. **While TTS plays, navigate to `/admin`:**
   visualiser disappears immediately; canvas is blank.
7. **Navigate back to chat:**
   visualiser reappears as soon as `ChatView` mounts and reports its
   bounds (within one frame).

## Tests

`visualiserRenderers.test.ts` — extend with geometry cases:

| Geometry | Expected `xOffset` | Expected `usableWidth` |
|----------|--------------------|------------------------|
| chatview = 1920px @ x=240, textCol = 768px @ x=816 (= centred in chat view, sidebar 240px on left) | 739.2 | 921.6 |
| chatview = 800px @ x=0, textCol = 768px @ x=16 (≈ centred, ≤ 1.2× threshold) | 0 | 800 |
| chatview = 768px @ x=0, textCol = 768px @ x=0 (mobile, equal) | 0 | 768 |
| chatview = 1000px @ x=0, textCol = 768px @ x=116 (= centred, no sidebar) | 39.2 | 921.6 |

## Out of Scope

- Vertical layout — the canvas stays fullscreen-fixed; bars stay
  vertically centred at `cy = height / 2`
- Animating width transitions when the sidebar toggles (a one-frame jump
  is acceptable for now)
- Changing what counts as "the text column" (e.g. switching to per-bubble
  width) — the bubble width varies per message, the `max-w-3xl` column
  is the stable reference
