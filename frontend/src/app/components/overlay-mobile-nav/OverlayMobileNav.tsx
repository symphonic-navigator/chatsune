import { useState } from 'react'
import { resolveCrumb } from './resolveCrumb'
import type { NavNode } from './types'

const EN_DASH = '–'

export interface OverlayMobileNavProps {
  tree: NavNode[]
  activeId: string
  onSelect: (id: string) => void
  /** Override the default gold; PersonaOverlay passes chakra.hex. */
  accentColour?: string
  /** Optional aria-label override for the trigger. */
  ariaLabel?: string
}

const DEFAULT_ACCENT = '#f5c542'

export function OverlayMobileNav({
  tree,
  activeId,
  onSelect: _onSelect,
  accentColour = DEFAULT_ACCENT,
  ariaLabel = 'Open navigation',
}: OverlayMobileNavProps) {
  const [open, _setOpen] = useState(false)
  const crumb = resolveCrumb(tree, activeId)

  // Keep these refs to silence unused-symbol lint warnings until later
  // tasks wire them up. The body of the component grows over the next
  // tasks (open/close toggle, panel content, keyboard nav).
  void _onSelect
  void _setOpen
  void open
  void accentColour
  void ariaLabel

  return (
    <button
      type="button"
      aria-haspopup="listbox"
      aria-expanded={open}
      className="w-full flex items-center justify-between rounded-md border border-white/12 bg-white/4 px-3 py-2.5"
    >
      <span className="text-[13px] font-medium text-white/92">
        {crumb.parent && (
          <>
            <span className="text-white/50 font-normal">{crumb.parent}</span>
            <span className="text-white/35 mx-1.5">{EN_DASH}</span>
          </>
        )}
        {crumb.leaf}
      </span>
      <span className="text-white/50 text-[14px]" aria-hidden>{open ? '▴' : '▾'}</span>
    </button>
  )
}
