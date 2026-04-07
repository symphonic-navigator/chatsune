# PersonaCard Redesign — Design Spec

**Date:** 2026-04-06
**Status:** Approved
**Addresses:** UX-006 (primary), plus model display enhancement

---

## Overview

Redesign the PersonaCard click interaction and menu bar. Replace the invisible split click zones (Continue 2/3, New 1/3) with a single click target (entire card body = Continue) and an explicit "New" button in the menu bar. Replace text labels in the menu bar with SVG icons. Add model name display below the tagline.

---

## Changes

### 1. Click Zones → Single Click Target

**Remove:** The absolute-positioned overlay div with two invisible click zones (`flex-[2]` Continue, `flex-[1]` New) and the hover-only divider between them. This is lines 190-245 in the current `PersonaCard.tsx`.

**Replace with:** The entire card body area (everything above the menu bar) becomes a single `<button>` or clickable `<div>` that calls `onContinue(persona.id)`.

**Hover hint:** On hover, show a subtle "▸ Continue" label positioned at the bottom of the card body (just above the menu bar). Style: `text-[9px]`, uppercase, `tracking-[1.5px]`, chakra colour at 50% opacity. Hidden when not hovered.

**Remove:** The `hoveredZone` state (`"continue" | "new" | null`) — no longer needed.

### 2. Menu Bar: Text → SVG Icons + New Button

**Current:** 3 text buttons: `Overview | Edit | History`

**New:** 4 icon buttons: `ℹ Info Circle | ✏ Pencil | 🕐 Clock | + Plus`

Each icon is an inline SVG, 14×14px, `stroke-width="2"`, `stroke-linecap="round"`, `stroke-linejoin="round"`. Default colour: `rgba(255,255,255,0.35)`. Hover: chakra colour + subtle background.

**SVG paths:**

**Info Circle (Overview):**
```html
<circle cx="12" cy="12" r="10"/>
<path d="M12 16v-4"/>
<path d="M12 8h.01"/>
```

**Pencil (Edit):**
```html
<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
<path d="m15 5 4 4"/>
```

**Clock (History):**
```html
<circle cx="12" cy="12" r="10"/>
<polyline points="12 6 12 12 16 14"/>
```

**Plus (New Chat):**
```html
<path d="M5 12h14"/>
<path d="M12 5v14"/>
```

The Plus icon has a slightly bolder stroke (`stroke-width="2.5"`) and uses the chakra colour at 70% opacity by default (not just on hover) to make it stand out as the primary action in the bar.

**Behaviour:** The first 3 icons call `onOpenOverlay(persona.id, tab)` as before. The Plus icon calls `onNewChat(persona.id)`.

**Tooltips:** Each button gets a `title` attribute: "Overview", "Edit", "History", "New Chat".

### 3. Model Name Display

Show the model slug below the tagline in the card body.

**Extraction:** From `persona.model_unique_id` (e.g. `ollama_cloud:llama3.2`), take everything after the first colon: `.split(":").slice(1).join(":")` → `llama3.2`.

**Style:** `font-family: 'Courier New', monospace`, `font-size: 9px`, `letter-spacing: 0.5px`, chakra colour at 30% opacity. Centred, below tagline.

---

## Unchanged

- Card dimensions, border, glow, gradient overlay
- Avatar/monogram area
- Name and tagline text
- Pin button and NSFW indicator
- Drag handle
- DnD sortable integration
- Card entrance animation

---

## Constraints

- No new dependencies
- All SVGs are inline (no icon library)
- `onContinue` and `onNewChat` props unchanged
- `onOpenOverlay` prop unchanged
