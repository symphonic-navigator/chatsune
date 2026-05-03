import type React from 'react'

/**
 * Visual treatment for pinned rows across sidebar zones and the
 * Personas-tab grid. A 3-px gold left border plus a barely-perceptible
 * warm tint. Padding compensates for the border so text aligns with
 * unpinned rows (subtract 3px from left padding at the call site).
 *
 * Per spec §2: this stripe replaces the legacy "Pinned" sub-headers and
 * per-row star icons.
 */
export const PINNED_STRIPE_STYLE: React.CSSProperties = {
  borderLeft: '3px solid rgba(212, 175, 55, 0.85)',
  background: 'rgba(212, 175, 55, 0.03)',
}
