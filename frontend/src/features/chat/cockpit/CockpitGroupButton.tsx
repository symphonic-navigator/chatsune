import { useEffect, useRef, useState, type ReactNode } from 'react'

type Props = {
  icon: ReactNode
  label: string
  children: ReactNode
  /**
   * Whether one of the contained buttons is in an active/enabled state.
   * When true, the trigger gets a subtle dot indicator so the user knows
   * something inside the collapsed group is on.
   */
  hasActiveChild?: boolean
  /**
   * Short marker text (1-2 chars) rendered in the bottom-left corner of
   * the trigger to surface persistent per-group state at a glance. Set
   * to ``null`` to hide. Decorative — the label / dropdown carry the
   * canonical state for assistive tech, so the badge is ``aria-hidden``
   * and ``pointer-events-none``. Used today for the "R" replay-history
   * marker (see spec
   * ``devdocs/specs/2026-05-17-replay-tool-history-toggle-ui-design.md``).
   */
  bottomLeftBadge?: string | null
}

/**
 * A cockpit trigger that expands upwards on click to reveal a row of child
 * buttons. Tap-friendly: toggle on click, close on outside click or Escape.
 * Used on mobile to collapse related actions (e.g. attach/camera/browse,
 * or tools/integrations) into a single slot.
 */
export function CockpitGroupButton({
  icon, label, children, hasActiveChild, bottomLeftBadge,
}: Props) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (!wrapperRef.current) return
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const base = 'cockpit-btn-fixed inline-flex items-center justify-center rounded-md border transition relative'
  const classes = open
    ? `${base} border-white/25 bg-white/10 text-white/90`
    : `${base} border-transparent bg-white/5 text-white/70 hover:bg-white/10`

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        title={label}
        className={classes}
        onClick={() => setOpen((v) => !v)}
      >
        {icon}
        {hasActiveChild && !open && (
          <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-[#d4af37] shadow-[0_0_4px_rgba(212,175,55,0.6)]" />
        )}
        {bottomLeftBadge && (
          <span
            aria-hidden="true"
            className="absolute bottom-0.5 left-0.5 text-[9px] font-semibold leading-none tracking-tight opacity-90 pointer-events-none"
          >
            {bottomLeftBadge}
          </span>
        )}
      </button>
      {open && (
        <div
          role="group"
          aria-label={label}
          className="absolute bottom-full left-0 mb-2 z-40 flex items-center gap-1.5 rounded-lg border border-white/10 bg-[#1a1625] px-2 py-1.5 shadow-xl"
          onClick={() => setOpen(false)}
        >
          {children}
        </div>
      )}
    </div>
  )
}
