# Design Spec — Nightfox Icon (Favicon + PWA)

**Date:** 2026-04-16
**Status:** Approved (brainstorming)
**Scope:** Replace the emoji-based favicon and the placeholder PWA icons
with a custom stylised fox icon in the Chatsune visual language.

## Motivation

The current setup uses `<text>🦊</text>` inside an SVG for both
`public/favicon.svg` and `public/pwa/icon.svg`. That renders
platform-dependently (Apple, Google, Microsoft all draw the fox differently)
and does not match Chatsune's opulent dark-purple aesthetic. The raster
assets (`apple-touch-icon.png`, `pwa/icon-192.png`, `pwa/icon-512.png`,
`pwa/icon-512-maskable.png`) are unrelated placeholders from the initial
scaffold and do not show a fox at all.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Motif | Front-facing fox head (symmetric) | Scales best from 16 px to 512 px; iconic and immediately legible |
| Right ear | Folded tip (showing inner glow) | Adds character asymmetry; distinctive silhouette; matches playful "companion" tone |
| Palette | Dark mystical "nightfox" | Fits Chatsune's opulent prototype style (`#0a0710` base, `#aa3bff` brand purple) |
| Eyes | Warm honey-gold with vertical slit pupil | High contrast against the dark head; reads clearly even at small sizes |
| Outer glow | Subtle purple halo via SVG filter | Silhouette stays legible against the dark app UI |
| Background | Transparent SVG; solid `#0a0710` for raster exports | Transparent for favicons and vector use; solid for PWA maskable safe-area compliance |

### Colour Palette

```
Head gradient    #5a3a82  →  #2e1c48  →  #120a1f   (radial, centre to edge)
Ear inner glow   #e9d5ff  →  #c084fc  →  #5b1e7a   (radial)
Eye              #fff4d4  →  #ffc86b  →  #c48938   (radial)
Pupil            #120a1f
Eye highlight    #ffffff
Snout / nose     #120a1f
Cheek glow       #aa3bff @ 28% → 0% (radial)
Outer aura       #aa3bff @ 55%, gaussian blur σ≈1.2 (SVG filter)
```

## SVG Source

Two variants are required. The full version carries the gradients, outer
glow and fine detail. The mini version is a flat-filled simplification
for ≤ 32 px renderings, where gradients blur into mud and thin strokes
disappear.

### `public/favicon.svg` and `public/pwa/icon.svg` (full)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-5 -5 110 110">
  <defs>
    <radialGradient id="headGrad" cx="50%" cy="38%" r="65%">
      <stop offset="0%"   stop-color="#5a3a82"/>
      <stop offset="55%"  stop-color="#2e1c48"/>
      <stop offset="100%" stop-color="#120a1f"/>
    </radialGradient>
    <radialGradient id="earGlow" cx="50%" cy="72%" r="70%">
      <stop offset="0%"   stop-color="#e9d5ff"/>
      <stop offset="45%"  stop-color="#c084fc"/>
      <stop offset="100%" stop-color="#5b1e7a"/>
    </radialGradient>
    <radialGradient id="eyeGrad" cx="50%" cy="40%" r="60%">
      <stop offset="0%"   stop-color="#fff4d4"/>
      <stop offset="50%"  stop-color="#ffc86b"/>
      <stop offset="100%" stop-color="#c48938"/>
    </radialGradient>
    <radialGradient id="cheekGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%"   stop-color="#aa3bff" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="#aa3bff" stop-opacity="0"/>
    </radialGradient>
    <filter id="outerGlow" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur in="SourceAlpha" stdDeviation="1.2" result="blur"/>
      <feFlood flood-color="#aa3bff" flood-opacity="0.55"/>
      <feComposite in2="blur" operator="in" result="glow"/>
      <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <g filter="url(#outerGlow)">
    <path d="M14 44 L28 6 L44 42 Z" fill="url(#headGrad)"/>
    <path d="M22 40 L28 14 L38 38 Z" fill="url(#earGlow)"/>
    <path d="M86 44 L76 22 L58 40 Z" fill="url(#headGrad)"/>
    <path d="M76 22 Q73 30 68 36 L62 32 Q70 28 76 22 Z" fill="url(#earGlow)"/>
    <path d="M76 22 L76 28 L71 32 Z" fill="#120a1f" opacity="0.6"/>
    <path d="M14 44 Q16 38 30 38 L50 32 L70 38 Q84 38 86 44 L66 74 Q50 90 34 74 Z" fill="url(#headGrad)"/>
    <ellipse cx="26" cy="58" rx="16" ry="10" fill="url(#cheekGlow)"/>
    <ellipse cx="74" cy="58" rx="16" ry="10" fill="url(#cheekGlow)"/>
    <path d="M50 54 L39 74 Q50 84 61 74 Z" fill="#3a2a50" opacity="0.5"/>
    <ellipse cx="36" cy="56" rx="5.3" ry="6.8" fill="url(#eyeGrad)"/>
    <ellipse cx="64" cy="56" rx="5.3" ry="6.8" fill="url(#eyeGrad)"/>
    <ellipse cx="36" cy="56" rx="1.4" ry="5" fill="#120a1f"/>
    <ellipse cx="64" cy="56" rx="1.4" ry="5" fill="#120a1f"/>
    <circle cx="37.4" cy="53.2" r="1.1" fill="#fff"/>
    <circle cx="65.4" cy="53.2" r="1.1" fill="#fff"/>
    <ellipse cx="50" cy="78" rx="3.6" ry="2.8" fill="#120a1f"/>
    <circle cx="49" cy="77" r="0.6" fill="#fff" opacity="0.55"/>
  </g>
</svg>
```

### `public/favicon-mini.svg` (flat, for ≤ 32 px)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-5 -5 110 110">
  <path d="M14 44 L28 6 L44 42 Z" fill="#2e1c48"/>
  <path d="M22 40 L28 14 L38 38 Z" fill="#aa3bff"/>
  <path d="M86 44 L76 22 L58 40 Z" fill="#2e1c48"/>
  <path d="M76 22 Q73 30 68 36 L62 32 Q70 28 76 22 Z" fill="#aa3bff"/>
  <path d="M14 44 Q16 38 30 38 L50 32 L70 38 Q84 38 86 44 L66 74 Q50 90 34 74 Z" fill="#2e1c48"/>
  <ellipse cx="36" cy="57" rx="6.5" ry="8" fill="#ffc86b"/>
  <ellipse cx="64" cy="57" rx="6.5" ry="8" fill="#ffc86b"/>
  <ellipse cx="36" cy="57" rx="1.6" ry="5.5" fill="#120a1f"/>
  <ellipse cx="64" cy="57" rx="1.6" ry="5.5" fill="#120a1f"/>
  <ellipse cx="50" cy="79" rx="5" ry="4" fill="#120a1f"/>
</svg>
```

## Target Files

All files live under `frontend/public/` and are referenced either by
`index.html` or by the `VitePWA` manifest in `frontend/vite.config.ts`.

| File | Purpose | Source | Notes |
|---|---|---|---|
| `favicon.svg` | Browser tab (vector) | Full SVG | Already referenced by `index.html` |
| `favicon.ico` | Legacy browser fallback | Rendered from mini SVG | 16 + 32 px multi-resolution ICO |
| `apple-touch-icon.png` | iOS home screen | Full SVG | 180 × 180, solid `#0a0710` background, no rounding (iOS applies squircle mask) |
| `pwa/icon.svg` | PWA vector icon | Full SVG | Referenced in manifest `icons[]` |
| `pwa/icon-192.png` | PWA Android launcher | Full SVG | 192 × 192, solid `#0a0710` background |
| `pwa/icon-512.png` | PWA large launcher, splash | Full SVG | 512 × 512, solid `#0a0710` background |
| `pwa/icon-512-maskable.png` | PWA maskable (adaptive icon) | Full SVG, scaled to 80 % safe area | 512 × 512, solid `#0a0710` background, fox fits inside central 80 % circle |

### Maskable Safe Area

The maskable PNG must render the full fox head inside the central
80 % circle (the Android "safe zone"). Our SVG already uses a
`viewBox="-5 -5 110 110"` which gives the outer glow 5 units of
padding on every side; for the maskable variant the fox is scaled to
80 % and centred in the 512 × 512 canvas, filling the remaining area
with the solid background colour.

## Variant Strategy

Two SVG sources exist, but only the **full** version is shipped as a
live asset. The **mini** version is a build-time input for the
legacy `.ico` only.

- `public/favicon.svg` — **full** SVG. The browser renders this at
  whatever size it wants (tab at 16 px, bookmark bar at 20 px, HiDPI
  at 32 px). At very small sizes gradients and the outer glow will
  blur slightly; this is an accepted trade-off so the brand look
  stays consistent across sizes.
- `public/pwa/icon.svg` — identical to `favicon.svg` (full).
- Raster PNG exports (`apple-touch-icon.png`, `pwa/icon-*.png`) are
  all rendered from the **full** SVG — their target sizes (180 +)
  easily carry the gradient detail.
- `public/favicon.ico` is rendered from the **mini** SVG at 16 + 32 px
  and packed into a multi-resolution `.ico`. The mini variant drops
  gradients and the outer glow, enlarges the honey-gold eyes, and
  keeps silhouettes crisp — this is the one place where the flat
  variant is actually used in a shipped asset.
- `public/favicon-mini.svg` is committed alongside as the source of
  truth for the mini variant but is not referenced from `index.html`
  or the manifest.

## HTML / Manifest Integration

Existing references already match this design — no wiring changes
needed, just asset replacement:

- `frontend/index.html:5`
  `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />`
- `frontend/index.html:6`
  `<link rel="apple-touch-icon" href="/apple-touch-icon.png" />`
- `frontend/vite.config.ts:35-42` (`includeAssets`) and lines 53-77
  (`manifest.icons`) already point at the target paths.

One addition: add `<link rel="alternate icon" href="/favicon.ico" />`
in `index.html` for legacy browser fallback (IE / older Android WebView).

## Out of Scope

- Animated variants (e.g. blinking eyes, flickering glow).
- Light-theme variant — the dark fox works on light backgrounds thanks
  to the purple aura; no second palette needed for now.
- Dynamic theming per persona — the icon is a brand mark, not a
  per-user asset.
- Splash-screen artwork beyond what the PWA manifest auto-generates
  from the icons.

## Acceptance Criteria

- All target files listed above exist under `frontend/public/` and load
  with HTTP 200 from a running `pnpm dev` server.
- `pnpm run build` succeeds and the built `dist/manifest.webmanifest`
  lists all four PWA icons with the correct `purpose` values.
- Visual check at 16 px (browser tab), 32 px (bookmarks), 180 px (iOS
  home screen), 192 + 512 px (Android launcher): fox is clearly
  recognisable, purple glow visible, eyes legible.
- Maskable PNG: when cropped to a central 80 % circle, no part of the
  fox head is cut off.
- Commit does not check in any generator intermediates (`*.xcf`,
  `*.afdesign`, etc.); only the source SVGs and the rendered final
  assets are tracked.
