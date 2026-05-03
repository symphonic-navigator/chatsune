import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useSidebarStore, type SidebarZone } from '../../../core/store/sidebarStore'

interface ZoneSectionProps {
  zone: SidebarZone
  title: string
  /** Called when the user clicks the header of an already-open zone, or
   *  on a closed zone too small to expand into, or on the More button.
   *  The zone never collapses via header click — switching to a different
   *  zone closes this one. */
  onOpenPage: () => void
  /** Empty CTA configuration. Renders only when `itemCount === 0`. */
  emptyState?: { label: string; onClick: () => void }
  itemCount: number
  /** Approximate item row height in px. Use a slight overestimate so
   *  the last item never gets clipped by overflow-hidden. */
  itemHeight?: number
  /** Render-prop receiving the maximum number of items that fit. */
  children: (visibleCount: number) => ReactNode
}

const FALLBACK_VISIBLE_COUNT = 10

/**
 * One of the sidebar entity zones.
 *
 * Accordion: at most one zone open at a time across the sidebar (the
 * sidebar store enforces this). Header click on the open zone opens its
 * full-management page; click on a closed zone expands it (and implicitly
 * closes the previously open one). Header layout: row is one button, with
 * a `›` chevron appended when open to telegraph "click leads to page".
 *
 * Item-count cap: the body is sized via flex-1 to share remaining space
 * with the action and footer blocks. A ResizeObserver measures the items
 * area (which excludes the always-visible More button at the bottom) and
 * computes how many items fit. The caller renders `visibleCount` items.
 *
 * Layout invariant: the More button is rendered OUTSIDE the measured /
 * overflow-hidden items area, so it can never be clipped — the items
 * area shrinks instead. Items beyond the cap are reachable via More or
 * the header click on the open zone.
 *
 * Edge case: if the zone is so small that NOT EVEN ONE item fits, header
 * click switches from "expand accordion" to "open page directly" — the
 * accordion would otherwise expand into nothing.
 */
export function ZoneSection({
  zone,
  title,
  onOpenPage,
  emptyState,
  itemCount,
  itemHeight = 36,
  children,
}: ZoneSectionProps) {
  const open = useSidebarStore((s) => s.openZone === zone)
  const setOpenZone = useSidebarStore((s) => s.setOpenZone)

  const bodyRef = useRef<HTMLDivElement | null>(null)
  const [bodyHeight, setBodyHeight] = useState<number>(0)

  useEffect(() => {
    const node = bodyRef.current
    if (!node) return
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height ?? 0
      setBodyHeight(h)
    })
    ro.observe(node)
    return () => ro.disconnect()
  }, [open])

  const visibleCount =
    bodyHeight > 0
      ? Math.max(0, Math.floor(bodyHeight / itemHeight))
      : FALLBACK_VISIBLE_COUNT

  const isEmpty = itemCount === 0
  // "No item fits" fallback applies only when there ARE items but none fit.
  const cannotFitAnyItem = open && !isEmpty && visibleCount === 0

  function handleHeaderClick() {
    if (open || cannotFitAnyItem) {
      // Already-open zone (or one too small to expand into) → go to the
      // full management page. The accordion never collapses to "all closed"
      // via header click; switching to a different zone closes this one.
      onOpenPage()
      return
    }
    setOpenZone(zone)
  }

  return (
    <section
      className={`flex min-h-0 flex-col ${open ? 'flex-1' : 'flex-none'}`}
      aria-label={title}
    >
      <button
        type="button"
        onClick={handleHeaderClick}
        className="flex flex-shrink-0 items-center gap-1 rounded px-3 py-1.5 text-left transition-colors hover:bg-white/5"
        aria-expanded={open}
        aria-label={open ? `Open all ${title.toLowerCase()}` : `Expand ${title}`}
        title={open ? `Open all ${title.toLowerCase()}` : `Expand ${title}`}
      >
        <span
          className={
            open
              ? 'flex-1 text-[11px] font-semibold uppercase tracking-wider text-gold'
              : 'flex-1 text-[11px] font-medium uppercase tracking-wider text-white/55'
          }
        >
          {title}
        </span>
        {open && (
          <span className="text-[10px] text-gold/60" aria-hidden="true">
            ›
          </span>
        )}
      </button>

      {open && (
        <>
          <div
            ref={bodyRef}
            className="min-h-0 flex-1 overflow-hidden"
          >
            {isEmpty && emptyState ? (
              <button
                type="button"
                onClick={emptyState.onClick}
                className="block w-full px-3 py-2 text-left text-[12px] text-white/45 transition-colors hover:text-white/70"
              >
                {emptyState.label}
              </button>
            ) : visibleCount > 0 ? (
              children(visibleCount)
            ) : null}
          </div>
          {!isEmpty && (
            <button
              type="button"
              onClick={onOpenPage}
              className="mx-3 mt-1 mb-1 flex flex-shrink-0 w-[calc(100%-24px)] items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-white/40 transition-colors hover:bg-white/5 hover:text-white/60"
            >
              <span>More… ›</span>
            </button>
          )}
        </>
      )}
    </section>
  )
}
