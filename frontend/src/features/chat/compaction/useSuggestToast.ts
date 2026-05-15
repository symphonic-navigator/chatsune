import { useEffect, useRef } from 'react'

interface Params {
  /** Latest known ``context_fill_percentage`` in the 0..1 range. */
  fillPercentage: number
  /**
   * Hard-suppress flag. When the user is in continuous-voice mode (live
   * conversation), the toast must never appear — there is no comfortable
   * way to interact with it hands-free, and the sparkly button stays
   * available on the desktop top-bar anyway.
   */
  isContinuousVoice: boolean
  /** Fired exactly once per up-cross of the 0.60 boundary. */
  onCross: () => void
}

/**
 * Detect the first transition of ``fillPercentage`` from ``< 0.60`` to
 * ``>= 0.60`` and invoke ``onCross``. After firing, the next call only
 * fires again when the percentage has dipped back below 0.60 and crossed
 * up again — which naturally happens after a successful compaction.
 *
 * The detector is **hard-suppressed** while ``isContinuousVoice`` is
 * true: see ``devdocs/specs/2026-05-15-compact-and-continue-design.md``
 * §5.3. The "last seen" value still tracks during voice mode so that
 * exiting voice mode does not artificially re-arm the detector.
 */
export function useSuggestToast({
  fillPercentage,
  isContinuousVoice,
  onCross,
}: Params): void {
  const lastSeen = useRef<number>(fillPercentage)
  useEffect(() => {
    const prev = lastSeen.current
    lastSeen.current = fillPercentage
    if (isContinuousVoice) return
    if (prev < 0.6 && fillPercentage >= 0.6) {
      onCross()
    }
  }, [fillPercentage, isContinuousVoice, onCross])
}
