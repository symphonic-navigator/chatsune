import type { ReactNode } from 'react'
import { useSidebarStore, type SidebarZone } from '../../../core/store/sidebarStore'

interface ZoneSectionProps {
  zone: SidebarZone
  title: string
  onAdd?: () => void
  /** Empty CTA configuration. Renders only when `isEmpty` is true. */
  emptyState?: { label: string; onClick: () => void }
  /** Whether the zone has zero items. Drives empty-state rendering. */
  isEmpty: boolean
  children: ReactNode
}

/**
 * One of the three sidebar entity zones.
 *
 * Header: title (uppercase, dimmed), optional `+`, collapse caret.
 * Body: scrollable when content overflows the flex-allocated max height.
 * Per-zone open state is persisted via sidebarStore.
 */
export function ZoneSection({
  zone,
  title,
  onAdd,
  emptyState,
  isEmpty,
  children,
}: ZoneSectionProps) {
  const open = useSidebarStore((s) => s.zoneOpen[zone])
  const toggleZone = useSidebarStore((s) => s.toggleZone)

  return (
    <section
      className={`flex min-h-0 flex-col ${open ? 'flex-1' : 'flex-none'}`}
      aria-label={title}
    >
      <header className="flex flex-shrink-0 items-center gap-1 px-3 py-1.5">
        <button
          type="button"
          onClick={() => toggleZone(zone)}
          className="flex flex-1 items-center gap-1 text-left"
          aria-expanded={open}
        >
          <span className="text-[11px] font-medium uppercase tracking-wider text-white/55">
            {title}
          </span>
        </button>
        {onAdd && (
          <button
            type="button"
            onClick={onAdd}
            aria-label={`Create ${title.toLowerCase()}`}
            title={`Create ${title.toLowerCase()}`}
            className="flex h-5 w-5 items-center justify-center rounded text-[12px] text-white/55 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            +
          </button>
        )}
        <button
          type="button"
          onClick={() => toggleZone(zone)}
          aria-label={open ? `Collapse ${title}` : `Expand ${title}`}
          title={open ? `Collapse ${title}` : `Expand ${title}`}
          className="flex h-5 w-5 items-center justify-center rounded text-[11px] text-white/55 transition-colors hover:bg-white/8 hover:text-white/85"
        >
          {open ? '∨' : '›'}
        </button>
      </header>

      {open && (
        <div className="min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
          {isEmpty && emptyState ? (
            <button
              type="button"
              onClick={emptyState.onClick}
              className="block w-full px-3 py-2 text-left text-[12px] text-white/45 transition-colors hover:text-white/70"
            >
              {emptyState.label}
            </button>
          ) : (
            children
          )}
        </div>
      )}
    </section>
  )
}
