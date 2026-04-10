import { useEffect, useState } from 'react'

/**
 * Viewport hook mirroring Tailwind's default breakpoints via `matchMedia`.
 *
 * Single source of truth for JS-side responsive decisions (drawer state,
 * conditional rendering, DnD activation constraints). CSS-only responsive
 * behaviour should still be expressed with Tailwind utilities — this hook is
 * only for cases where CSS alone is insufficient.
 *
 * Breakpoints follow Tailwind defaults:
 *   sm >= 640, md >= 768, lg >= 1024, xl >= 1280.
 *
 * The project targets two layout tiers ("compact" < lg, "desktop" >= lg),
 * hence `isMobile` / `isDesktop` are the primary flags. The individual
 * breakpoint booleans are provided for finer-grained needs.
 *
 * Uses `matchMedia` change listeners only — no resize polling.
 */

const BREAKPOINTS = {
  sm: '(min-width: 640px)',
  md: '(min-width: 768px)',
  lg: '(min-width: 1024px)',
  xl: '(min-width: 1280px)',
  landscape: '(orientation: landscape)',
} as const

type BreakpointKey = keyof typeof BREAKPOINTS

export interface ViewportState {
  /** True while viewport is below the `lg` breakpoint (< 1024 px). */
  isMobile: boolean
  /** True between `md` and `lg` (>= 768 and < 1024). */
  isTablet: boolean
  /** True at or above the `lg` breakpoint (>= 1024 px). */
  isDesktop: boolean
  /** True when below lg AND orientation is landscape. */
  isLandscape: boolean
  isSm: boolean
  isMd: boolean
  isLg: boolean
  isXl: boolean
}

function readMatches(): Record<BreakpointKey, boolean> {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    // Defensive fallback for non-browser contexts. CSR-only project, but the
    // guard keeps the module import-safe under tests / SSR tooling.
    return { sm: false, md: false, lg: false, xl: false, landscape: false }
  }
  return {
    sm: window.matchMedia(BREAKPOINTS.sm).matches,
    md: window.matchMedia(BREAKPOINTS.md).matches,
    lg: window.matchMedia(BREAKPOINTS.lg).matches,
    xl: window.matchMedia(BREAKPOINTS.xl).matches,
    landscape: window.matchMedia(BREAKPOINTS.landscape).matches,
  }
}

function deriveState(matches: Record<BreakpointKey, boolean>): ViewportState {
  return {
    isMobile: !matches.lg,
    isTablet: matches.md && !matches.lg,
    isDesktop: matches.lg,
    isLandscape: !matches.lg && matches.landscape,
    isSm: matches.sm,
    isMd: matches.md,
    isLg: matches.lg,
    isXl: matches.xl,
  }
}

export function useViewport(): ViewportState {
  const [state, setState] = useState<ViewportState>(() => deriveState(readMatches()))

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }

    const lists: MediaQueryList[] = (Object.keys(BREAKPOINTS) as BreakpointKey[]).map((key) =>
      window.matchMedia(BREAKPOINTS[key]),
    )

    const handleChange = () => {
      setState(deriveState(readMatches()))
    }

    // Ensure state is in sync on mount — avoids a stale initial render if the
    // viewport changed between `useState` init and effect attach.
    handleChange()

    lists.forEach((list) => list.addEventListener('change', handleChange))
    return () => {
      lists.forEach((list) => list.removeEventListener('change', handleChange))
    }
  }, [])

  return state
}
