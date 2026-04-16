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

# NOTE: public/pwa/icon.svg is kept as a byte-identical copy of public/favicon.svg.
#       If you edit the full SVG, update both files, then re-run this script.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_DIR="$SCRIPT_DIR/../public"
BG="#0a0710"

command -v rsvg-convert >/dev/null || { echo "error: rsvg-convert not found (install librsvg)" >&2; exit 1; }
command -v magick        >/dev/null || { echo "error: magick not found (install imagemagick v7)" >&2; exit 1; }

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

cd "$PUBLIC_DIR"
mkdir -p pwa

echo "==> apple-touch-icon.png (180x180)"
rsvg-convert -w 180 -h 180 -b "$BG" favicon.svg -o apple-touch-icon.png

echo "==> pwa/icon-192.png (192x192)"
rsvg-convert -w 192 -h 192 -b "$BG" favicon.svg -o pwa/icon-192.png

echo "==> pwa/icon-512.png (512x512)"
rsvg-convert -w 512 -h 512 -b "$BG" favicon.svg -o pwa/icon-512.png

echo "==> pwa/icon-512-maskable.png (fox at 80% central, 512x512 canvas)"
# 80% of 512 = 410 px. Render fox transparent at 410, composite onto solid 512 canvas.
rsvg-convert -w 410 -h 410 favicon.svg \
  | magick -size 512x512 "xc:${BG}" - -gravity center -composite -depth 8 pwa/icon-512-maskable.png

echo "==> favicon.ico (16 + 32 px, from mini SVG)"
rsvg-convert -w 16 -h 16 favicon-mini.svg -o "$TMPDIR/fav-16.png"
rsvg-convert -w 32 -h 32 favicon-mini.svg -o "$TMPDIR/fav-32.png"
magick "$TMPDIR/fav-16.png" "$TMPDIR/fav-32.png" favicon.ico

echo
echo "Generated:"
for f in favicon.ico apple-touch-icon.png pwa/icon-192.png pwa/icon-512.png pwa/icon-512-maskable.png; do
  [ -f "$f" ] || { echo "  MISSING: $f" >&2; exit 1; }
  size=$(magick identify -format '%wx%h' "$f")
  bytes=$(stat -c '%s' "$f")
  echo "  $f  ($size, ${bytes} bytes)"
done
