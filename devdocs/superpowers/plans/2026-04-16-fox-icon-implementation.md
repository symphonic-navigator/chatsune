# Nightfox Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the emoji-based favicon and placeholder PWA raster icons with the Nightfox icon (custom stylised fox, dark-purple head gradient, honey-gold eyes, purple outer glow), shipping favicon SVG + ICO, Apple-Touch PNG, and PWA PNGs (normal + maskable).

**Architecture:** Two hand-written SVG sources (`favicon.svg` full, `favicon-mini.svg` flat) live under `frontend/public/`. A shell build script under `frontend/scripts/build-icons.sh` renders all raster outputs via `rsvg-convert` (SVG → PNG) and ImageMagick `magick` (PNG → ICO, maskable composite). Generated binaries are committed to the repo — the script runs on demand (`pnpm run build:icons`), not during Vite builds or Docker builds.

**Tech Stack:** raw SVG · `rsvg-convert` 2.62+ (from `librsvg`) · ImageMagick 7 (`magick` binary) · existing VitePWA setup in `frontend/vite.config.ts`.

**Spec reference:** [`docs/superpowers/specs/2026-04-16-fox-icon-design.md`](../specs/2026-04-16-fox-icon-design.md)

---

## File Structure

**Create:**
- `frontend/public/favicon.svg` — full Nightfox SVG (gradients + outer glow)
- `frontend/public/favicon-mini.svg` — flat Nightfox SVG (ICO source)
- `frontend/public/pwa/icon.svg` — identical to `favicon.svg`; separate file because VitePWA references it explicitly
- `frontend/scripts/build-icons.sh` — one-shot asset build script

**Generate (via build-icons.sh, committed as binaries):**
- `frontend/public/favicon.ico` — 16 + 32 px multi-resolution ICO from mini SVG
- `frontend/public/apple-touch-icon.png` — 180 × 180, solid `#0a0710` bg
- `frontend/public/pwa/icon-192.png` — 192 × 192, solid `#0a0710` bg
- `frontend/public/pwa/icon-512.png` — 512 × 512, solid `#0a0710` bg
- `frontend/public/pwa/icon-512-maskable.png` — 512 × 512, fox at ~80 % central, solid `#0a0710` bg

**Modify:**
- `frontend/index.html` — add `<link rel="alternate icon" href="/favicon.ico" />`
- `frontend/package.json` — add `build:icons` script entry

**Do not modify:**
- `frontend/vite.config.ts` — `includeAssets` and `manifest.icons` already point at the right paths; no changes needed.

---

## Task 1: Verify toolchain

**Files:** (none)

- [ ] **Step 1: Verify `rsvg-convert` is available and new enough**

Run: `rsvg-convert --version`
Expected: version ≥ `2.58` (SVG filter support). On Arch it is shipped by the `librsvg` package.

- [ ] **Step 2: Verify ImageMagick v7 `magick` is available**

Run: `magick --version | head -1`
Expected: line starts with `Version: ImageMagick 7.`

- [ ] **Step 3: If either tool is missing, install it**

```bash
# Arch:
sudo pacman -S --needed librsvg imagemagick
```

Do not commit anything in this task. If both tools are present, move on.

---

## Task 2: Create the full Nightfox SVG

**Files:**
- Create: `frontend/public/favicon.svg`

- [ ] **Step 1: Write `frontend/public/favicon.svg`**

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

- [ ] **Step 2: Quick rendering check**

Run: `rsvg-convert -w 256 -h 256 frontend/public/favicon.svg -o /tmp/fox-check.png && file /tmp/fox-check.png`
Expected: `/tmp/fox-check.png: PNG image data, 256 x 256, ...`
Open `/tmp/fox-check.png` in an image viewer — you should see the fox head with visible purple aura around it (proof that the SVG filter rendered).

- [ ] **Step 3: Commit**

```bash
git add frontend/public/favicon.svg
git commit -m "Replace emoji favicon with full Nightfox SVG source"
```

---

## Task 3: Create the flat mini SVG

**Files:**
- Create: `frontend/public/favicon-mini.svg`

- [ ] **Step 1: Write `frontend/public/favicon-mini.svg`**

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

- [ ] **Step 2: Rendering check at favicon size**

Run: `rsvg-convert -w 16 -h 16 frontend/public/favicon-mini.svg -o /tmp/fox-16.png && file /tmp/fox-16.png`
Expected: `/tmp/fox-16.png: PNG image data, 16 x 16, ...`

Open the file — even at 16 px the two ears, the two bright eyes, and the dark snout should be distinguishable.

- [ ] **Step 3: Commit**

```bash
git add frontend/public/favicon-mini.svg
git commit -m "Add flat Nightfox SVG for ICO rendering at small sizes"
```

---

## Task 4: Duplicate the full SVG as the PWA icon

**Files:**
- Create: `frontend/public/pwa/icon.svg`

The VitePWA manifest in `frontend/vite.config.ts:55` references `/pwa/icon.svg` explicitly. We ship an identical copy rather than a symlink so the file is available in the final `dist/` build output regardless of OS or Docker filesystem quirks.

- [ ] **Step 1: Copy the full SVG into the PWA folder**

Run:
```bash
cp frontend/public/favicon.svg frontend/public/pwa/icon.svg
```

- [ ] **Step 2: Verify byte-identical copy**

Run: `diff -q frontend/public/favicon.svg frontend/public/pwa/icon.svg`
Expected: no output (files are identical).

- [ ] **Step 3: Commit**

```bash
git add frontend/public/pwa/icon.svg
git commit -m "Ship Nightfox as PWA vector icon"
```

---

## Task 5: Create the icon build script

**Files:**
- Create: `frontend/scripts/build-icons.sh`

- [ ] **Step 1: Create the scripts directory**

Run: `mkdir -p frontend/scripts`

- [ ] **Step 2: Write `frontend/scripts/build-icons.sh`**

```bash
#!/usr/bin/env bash
# Render all raster icon assets from the two SVG sources.
# Inputs:  public/favicon.svg (full), public/favicon-mini.svg (flat)
# Outputs: public/favicon.ico
#          public/apple-touch-icon.png
#          public/pwa/icon-192.png
#          public/pwa/icon-512.png
#          public/pwa/icon-512-maskable.png
#
# Run via: pnpm run build:icons  (from the frontend/ directory)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_DIR="$SCRIPT_DIR/../public"
BG="#0a0710"

command -v rsvg-convert >/dev/null || { echo "error: rsvg-convert not found (install librsvg)" >&2; exit 1; }
command -v magick        >/dev/null || { echo "error: magick not found (install imagemagick v7)" >&2; exit 1; }

cd "$PUBLIC_DIR"

echo "==> apple-touch-icon.png (180x180)"
rsvg-convert -w 180 -h 180 -b "$BG" favicon.svg -o apple-touch-icon.png

echo "==> pwa/icon-192.png (192x192)"
rsvg-convert -w 192 -h 192 -b "$BG" favicon.svg -o pwa/icon-192.png

echo "==> pwa/icon-512.png (512x512)"
rsvg-convert -w 512 -h 512 -b "$BG" favicon.svg -o pwa/icon-512.png

echo "==> pwa/icon-512-maskable.png (fox at 80% central, 512x512 canvas)"
# 80% of 512 = 410 px. Render fox transparent at 410, composite onto solid 512 canvas.
rsvg-convert -w 410 -h 410 favicon.svg \
  | magick -size 512x512 "xc:${BG}" - -gravity center -composite pwa/icon-512-maskable.png

echo "==> favicon.ico (16 + 32 px, from mini SVG)"
rsvg-convert -w 16 -h 16 favicon-mini.svg -o /tmp/fox-fav-16.png
rsvg-convert -w 32 -h 32 favicon-mini.svg -o /tmp/fox-fav-32.png
magick /tmp/fox-fav-16.png /tmp/fox-fav-32.png favicon.ico
rm -f /tmp/fox-fav-16.png /tmp/fox-fav-32.png

echo
echo "Generated:"
for f in favicon.ico apple-touch-icon.png pwa/icon-192.png pwa/icon-512.png pwa/icon-512-maskable.png; do
  [ -f "$f" ] || { echo "  MISSING: $f" >&2; exit 1; }
  size=$(magick identify -format '%wx%h' "$f")
  bytes=$(stat -c '%s' "$f")
  echo "  $f  ($size, ${bytes} bytes)"
done
```

- [ ] **Step 3: Make it executable**

Run: `chmod +x frontend/scripts/build-icons.sh`

- [ ] **Step 4: Commit the script**

```bash
git add frontend/scripts/build-icons.sh
git commit -m "Add icon build script using rsvg-convert and ImageMagick"
```

---

## Task 6: Wire the script into pnpm

**Files:**
- Modify: `frontend/package.json` (the `scripts` block)

- [ ] **Step 1: Add the `build:icons` entry**

Open `frontend/package.json`. In the `"scripts"` object, add a new entry alongside `dev`, `build`, `lint`, `preview`:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview",
    "build:icons": "bash scripts/build-icons.sh"
  },
```

(Only `"build:icons": "bash scripts/build-icons.sh"` is new — the other lines are shown for context.)

- [ ] **Step 2: Verify pnpm picks it up**

Run: `cd frontend && pnpm run`
Expected output contains a line like `build:icons` under the scripts listing.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json
git commit -m "Add build:icons pnpm script"
```

---

## Task 7: Render the assets

**Files:**
- Generate: `frontend/public/favicon.ico`
- Generate: `frontend/public/apple-touch-icon.png`
- Generate: `frontend/public/pwa/icon-192.png`
- Generate: `frontend/public/pwa/icon-512.png`
- Generate: `frontend/public/pwa/icon-512-maskable.png`

- [ ] **Step 1: Run the build**

Run:
```bash
cd frontend && pnpm run build:icons
```

Expected output:
```
==> apple-touch-icon.png (180x180)
==> pwa/icon-192.png (192x192)
==> pwa/icon-512.png (512x512)
==> pwa/icon-512-maskable.png (fox at 80% central, 512x512 canvas)
==> favicon.ico (16 + 32 px, from mini SVG)

Generated:
  favicon.ico  (32x32, <N> bytes)
  apple-touch-icon.png  (180x180, <N> bytes)
  pwa/icon-192.png  (192x192, <N> bytes)
  pwa/icon-512.png  (512x512, <N> bytes)
  pwa/icon-512-maskable.png  (512x512, <N> bytes)
```

(ImageMagick reports the size of the largest layer of an ICO, so `favicon.ico` shows as `32x32` even though it contains both 16 and 32.)

- [ ] **Step 2: Visual spot-check**

Open two files in an image viewer:
- `frontend/public/pwa/icon-512.png` — fox fills most of the frame, purple aura visible around the silhouette, honey-gold eyes with black slit pupils, folded right ear, solid dark background.
- `frontend/public/pwa/icon-512-maskable.png` — fox is visibly smaller and centred; there is a uniform dark border around it (≥ 50 px on each side).

If either looks off (fox cut off, no aura, wrong colours), stop and report — do not proceed to commit.

- [ ] **Step 3: Verify ICO contains both sizes**

Run: `magick identify frontend/public/favicon.ico`
Expected: two lines of output, one `16x16` and one `32x32`.

- [ ] **Step 4: Commit the generated assets**

```bash
git add frontend/public/favicon.ico \
        frontend/public/apple-touch-icon.png \
        frontend/public/pwa/icon-192.png \
        frontend/public/pwa/icon-512.png \
        frontend/public/pwa/icon-512-maskable.png
git commit -m "Render Nightfox raster assets (favicon.ico + PWA PNGs)"
```

---

## Task 8: Add the legacy-favicon link

**Files:**
- Modify: `frontend/index.html:5-6`

- [ ] **Step 1: Add the `alternate icon` link**

Open `frontend/index.html`. Current lines 5–6:

```html
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
```

Insert a new line between them so the result is:

```html
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="alternate icon" href="/favicon.ico" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "Link favicon.ico as legacy fallback"
```

---

## Task 9: Build verification

**Files:** (none — verification only)

- [ ] **Step 1: Run the production build**

Run:
```bash
cd frontend && pnpm run build
```

Expected: build completes without errors. The final lines include something like `✓ built in <N>s` and list precached PWA assets.

- [ ] **Step 2: Verify the manifest lists all four icons**

Run: `cat frontend/dist/manifest.webmanifest | python -m json.tool`
Expected: the `"icons"` array contains exactly four entries with these `src` values:
- `/pwa/icon.svg`  (purpose `any`)
- `/pwa/icon-192.png`  (purpose `any`)
- `/pwa/icon-512.png`  (purpose `any`)
- `/pwa/icon-512-maskable.png`  (purpose `maskable`)

- [ ] **Step 3: Verify each referenced file exists in `dist/`**

Run:
```bash
cd frontend && for f in favicon.svg favicon.ico apple-touch-icon.png pwa/icon.svg pwa/icon-192.png pwa/icon-512.png pwa/icon-512-maskable.png; do
  [ -f "dist/$f" ] && echo "OK  dist/$f" || echo "MISS dist/$f"
done
```

Expected: seven `OK` lines, zero `MISS`.

- [ ] **Step 4: Live check against the dev server (manual)**

Run: `cd frontend && pnpm run dev`
Open `http://localhost:5173` in a browser. Check:
- Browser tab icon shows the fox (not the Vite "V" and not the emoji).
- Open DevTools → Application → Manifest: all four icons load without 404.
- Open DevTools → Application → Manifest → Maskable preview: the fox fits entirely inside the circle with margin.

Stop the dev server with Ctrl-C when done.

- [ ] **Step 5: Final commit (only if anything changed during verification)**

If steps 1-4 revealed nothing to fix, this task makes no commit. If they did, commit the fix and re-run from Step 1.

---

## Self-Review Notes

**Spec coverage:**
- Motif + style decisions → captured as-is in Tasks 2-4 (SVG sources).
- Full vs mini variant strategy → encoded in Task 5's build script (full for all sizes > 32 px; mini only for `favicon.ico`).
- Maskable safe-area (80 % centre) → Task 5 renders the fox at 410 px and composites onto a 512 × 512 solid canvas, which satisfies the 80 % guideline (410 / 512 ≈ 0.80).
- `<link rel="alternate icon">` addition → Task 8.
- Acceptance criteria (pnpm build clean, manifest lists four icons, visual check, maskable safe-area) → Task 9 steps 1-4.

**Risks:**
- Older `rsvg-convert` (< 2.58) has known gaps in SVG filter rendering; the outer glow may not appear. Task 1 verifies version. Fallback if it breaks on a future system: remove the `<filter>` from `favicon.svg` and replace with a second stroked path behind the head — but with 2.62.1 in hand this is not expected.
- The `pwa/icon.svg` being a byte-identical copy of `favicon.svg` means future edits must touch both files or introduce a build step. For now, two files is simpler than adding tooling.

**Out of scope for this plan (from spec):** animated variants, light-theme variant, per-persona theming, splash-screen artwork beyond what VitePWA auto-generates.
