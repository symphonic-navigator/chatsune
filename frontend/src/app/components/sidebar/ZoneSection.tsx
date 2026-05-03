import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useSidebarStore, type SidebarZone } from '../../../core/store/sidebarStore'

interface ZoneSectionProps {
  zone: SidebarZone
  title: string
  /** Called when the user clicks the header of an already-open zone, or
   *  on a closed zone too small to expand into. The zone never collapses
   *  via header click — switching to a different zone closes this one. */
  onOpenPage: () => void
  /** Empty CTA configuration. Renders only when `itemCount === 0`. */
  emptyState?: { label: string; onClick: () => void }
  itemCount: number
  /** Approximate item row height in px. Used to compute how many
   *  items fit before the More button. */
  itemHeight?: number
  /** Render-prop receiving the maximum number of items that fit. */
  children: (visibleCount: number) => ReactNode
}

const MORE_BUTTON_HEIGHT = 28
const FALLBACK_VISIBLE_COUNT = 10

/**
 * One of the sidebar entity zones.
 *
 * Accordion: at most one zone open at a time across the sidebar (the
 * sidebar store enforces this). Header click toggles open; clicking the
 * already-open header collapses to the all-closed state.
 *
 * Item-count cap: the body is sized via flex-1 to share remaining space
 * with sibling sections. A ResizeObserver measures the body and computes
 * how many items fit without scrolling. The caller renders `visibleCount`
 * items; anything beyond is reachable via the More button (or the always-
 * visible `…` header button).
 *
 * Edge case: if the zone is so small that NOT EVEN ONE item fits, header
 * click switches from "toggle accordion" to "open page directly" — the
 * accordion would otherwise expand into nothing.
 */
export function ZoneSection({
  zone,
  title,
  onOpenPage,
  emptyState,
  itemCount,
  itemHeight = 32,
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
      ? Math.max(0, Math.floor((bodyHeight - MORE_BUTTON_HEIGHT) / itemHeight))
      : FALLBACK_VISIBLE_COUNT

  const isEmpty = itemCount === 0
  // Only the "no item fits" fallback — empty data still uses the CTA.
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
              ? 'text-[11px] font-semibold uppercase tracking-wider text-gold'
              : 'text-[11px] font-medium uppercase tracking-wider text-white/55'
          }
        >
          {title}
        </span>
      </button>

      {open && (
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
      )}
    </section>
  )
}
