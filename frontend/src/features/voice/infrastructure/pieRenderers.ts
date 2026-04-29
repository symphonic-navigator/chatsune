import type { VisualiserStyle } from '../stores/voiceSettingsStore'

export interface PieRenderOpts {
  /** Pie centre, canvas pixels. */
  cx: number
  cy: number
  /** Outer radius, canvas pixels. */
  radius: number
  /** 0..1 fraction of the redemption window still remaining. */
  remainingFraction: number
  /** Persona accent colour, 0–255. */
  rgb: [number, number, number]
  /** Lightened persona colour for highlights. */
  rgbLight: [number, number, number]
  /** Master opacity, 0..1 (matches the visualiser's setting). */
  opacity: number
}

const TWO_PI = Math.PI * 2
/** 12 o'clock, matching an iOS-style countdown timer. */
const START_ANGLE = -Math.PI / 2

export function drawPieFrame(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  opts: PieRenderOpts,
): void {
  const frac = Math.min(1, Math.max(0, opts.remainingFraction))
  if (frac <= 0) return

  const endAngle = START_ANGLE + frac * TWO_PI

  switch (style) {
    case 'sharp': drawPieSharp(ctx, opts, endAngle); break
    case 'soft':  drawPieSoft(ctx, opts, endAngle); break
    case 'glow':  drawPieGlow(ctx, opts, endAngle); break
    case 'glass': drawPieGlass(ctx, opts, endAngle); break
  }
}

function tracePie(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  ctx.beginPath()
  ctx.moveTo(o.cx, o.cy)
  ctx.arc(o.cx, o.cy, o.radius, START_ANGLE, endAngle)
  ctx.closePath()
}

function drawPieSharp(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [lr, lg, lb] = o.rgbLight
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity})`
  tracePie(ctx, o, endAngle)
  ctx.fill()
}

function drawPieSoft(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  const grd = ctx.createRadialGradient(o.cx, o.cy, 0, o.cx, o.cy, o.radius)
  grd.addColorStop(0,   `rgba(${lr},${lg},${lb},${o.opacity})`)
  grd.addColorStop(0.6, `rgba(${r},${g},${b},${o.opacity * 0.85})`)
  grd.addColorStop(1,   `rgba(${r},${g},${b},${o.opacity * 0.25})`)
  ctx.fillStyle = grd
  tracePie(ctx, o, endAngle)
  ctx.fill()
}

function drawPieGlow(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  ctx.shadowColor = `rgba(${r},${g},${b},${o.opacity * 1.5})`
  ctx.shadowBlur = 14
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.9})`
  tracePie(ctx, o, endAngle)
  ctx.fill()
  ctx.shadowBlur = 0
}

function drawPieGlass(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [lr, lg, lb] = o.rgbLight
  // Milky core fill.
  ctx.fillStyle = `rgba(255,255,255,${o.opacity * 0.45})`
  tracePie(ctx, o, endAngle)
  ctx.fill()
  // Coloured stroke around the wedge — matches visualiser's drawGlass convention.
  ctx.strokeStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.85})`
  ctx.lineWidth = 1
  tracePie(ctx, o, endAngle)
  ctx.stroke()
}
