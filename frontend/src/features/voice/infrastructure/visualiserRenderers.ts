import type { VisualiserStyle } from '../stores/voiceSettingsStore'
import type { Bounds } from '../stores/visualiserLayoutStore'

export interface RenderOpts {
  /** RGB triplet, 0–255 each, of the persona's chakra colour. */
  rgb: [number, number, number]
  /** Same colour brightened by ~+40 per channel, clamped to 255. */
  rgbLight: [number, number, number]
  /** User-configured opacity, 0.05–0.80. */
  opacity: number
  /** Hard-coded fraction of viewport height occupied by total deflection. */
  maxHeightFraction: number
}

export interface BarGeometry {
  /** Inner-of-sidebars area, viewport-relative. */
  chatview: Bounds
  /** Centred message column, viewport-relative. */
  textColumn: Bounds
}

/**
 * Render a frame of the equaliser for the requested style. Caller has
 * already cleared the canvas. `bins` is normalised to [0, 1].
 */
export function drawVisualiserFrame(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  height: number,
  bins: Float32Array,
  opts: RenderOpts,
  geometry: BarGeometry,
): void {
  switch (style) {
    case 'sharp': drawSharp(ctx, height, bins, opts, geometry); break
    case 'soft':  drawSoft(ctx, height, bins, opts, geometry); break
    case 'glow':  drawGlow(ctx, height, bins, opts, geometry); break
    case 'glass': drawGlass(ctx, height, bins, opts, geometry); break
  }
}


export function barLayout(
  height: number,
  n: number,
  frac: number,
  geometry: BarGeometry,
): { cy: number; slot: number; barW: number; maxDy: number; xOffset: number } {
  const { chatview, textColumn } = geometry
  const target = textColumn.w * 1.2
  const usable = Math.min(target, chatview.w)
  const centre = textColumn.x + textColumn.w / 2
  const left = Math.max(chatview.x, centre - usable / 2)
  const right = Math.min(chatview.x + chatview.w, centre + usable / 2)
  const xOffset = left
  const finalWidth = right - left
  const cy = height / 2
  const slot = finalWidth / n
  const barW = slot * 0.62
  const maxDy = (height * frac) / 2
  return { cy, slot, barW, maxDy, xOffset }
}

const DOT_BASE_RADIUS = 7
const DOT_GAP = 22

export function dotLayout(geometry: BarGeometry): {
  centreX: number
  dotXs: [number, number, number]
  baseRadius: number
  gap: number
} {
  // Same clamping rules as barLayout so the dots stay centred on the
  // same visual extent as the bars (≤ 1.2 × textColumn, but never wider
  // than chatview).
  const { chatview, textColumn } = geometry
  const target = textColumn.w * 1.2
  const usable = Math.min(target, chatview.w)
  const tcCentre = textColumn.x + textColumn.w / 2
  const left = Math.max(chatview.x, tcCentre - usable / 2)
  const right = Math.min(chatview.x + chatview.w, tcCentre + usable / 2)
  const centreX = (left + right) / 2
  return {
    centreX,
    dotXs: [centreX - DOT_GAP, centreX, centreX + DOT_GAP],
    baseRadius: DOT_BASE_RADIUS,
    gap: DOT_GAP,
  }
}

function drawSharp(ctx: CanvasRenderingContext2D, h: number, bins: Float32Array, o: RenderOpts, g: BarGeometry) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(h, n, o.maxHeightFraction, g)
  const [lr, lg, lb] = o.rgbLight
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity})`
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    ctx.fillRect(xOffset + i * slot + (slot - barW) / 2, cy - dy, barW, dy * 2)
  }
}

function drawSoft(ctx: CanvasRenderingContext2D, h: number, bins: Float32Array, o: RenderOpts, geom: BarGeometry) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(h, n, o.maxHeightFraction, geom)
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    const y0 = cy - dy
    const grd = ctx.createLinearGradient(0, y0, 0, cy + dy)
    grd.addColorStop(0,   `rgba(${r},${g},${b},${o.opacity * 0.15})`)
    grd.addColorStop(0.5, `rgba(${lr},${lg},${lb},${o.opacity})`)
    grd.addColorStop(1,   `rgba(${r},${g},${b},${o.opacity * 0.15})`)
    ctx.fillStyle = grd
    ctx.fillRect(xOffset + i * slot + (slot - barW) / 2, y0, barW, dy * 2)
  }
}

function drawGlow(ctx: CanvasRenderingContext2D, h: number, bins: Float32Array, o: RenderOpts, geom: BarGeometry) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(h, n, o.maxHeightFraction, geom)
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  ctx.shadowColor = `rgba(${r},${g},${b},${o.opacity * 1.5})`
  ctx.shadowBlur = 14
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.9})`
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    ctx.fillRect(xOffset + i * slot + (slot - barW) / 2, cy - dy, barW, dy * 2)
  }
  ctx.shadowBlur = 0
}

function drawGlass(ctx: CanvasRenderingContext2D, h: number, bins: Float32Array, o: RenderOpts, g: BarGeometry) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(h, n, o.maxHeightFraction, g)
  const [lr, lg, lb] = o.rgbLight
  ctx.lineWidth = 1
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    const x = xOffset + i * slot + (slot - barW) / 2
    const y0 = cy - dy
    ctx.fillStyle = `rgba(255,255,255,${o.opacity * 0.45})`
    ctx.fillRect(x, y0, barW, dy * 2)
    ctx.strokeStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.85})`
    ctx.strokeRect(x + 0.5, y0 + 0.5, barW - 1, dy * 2 - 1)
  }
}
