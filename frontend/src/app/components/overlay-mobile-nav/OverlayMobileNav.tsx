import { useEffect, useId, useState } from 'react'
import { resolveCrumb } from './resolveCrumb'
import { isSection, type NavLeaf, type NavNode } from './types'

const EN_DASH = '–'
const DEFAULT_ACCENT = '#f5c542'

export interface OverlayMobileNavProps {
  tree: NavNode[]
  activeId: string
  onSelect: (id: string) => void
  /** Override the default gold; PersonaOverlay passes chakra.hex. */
  accentColour?: string
  /** Optional aria-label override for the trigger. */
  ariaLabel?: string
}

export function OverlayMobileNav({
  tree,
  activeId,
  onSelect,
  accentColour = DEFAULT_ACCENT,
  ariaLabel = 'Open navigation',
}: OverlayMobileNavProps) {
  const [open, setOpen] = useState(false)
  const crumb = resolveCrumb(tree, activeId)
  const panelId = useId()

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function handleLeafClick(leaf: NavLeaf) {
    onSelect(leaf.id)
    setOpen(false)
  }

  // Temporary scaffolding — used in later tasks.
  void accentColour

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
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

      {open && (
        <>
          <div
            data-testid="overlay-mobile-nav-backdrop"
            aria-hidden
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-20"
          />
          <ul
            id={panelId}
            role="listbox"
            className="absolute left-0 right-0 mt-1.5 max-h-[min(70vh,460px)] overflow-y-auto rounded-md border border-white/12 bg-[#13101e] shadow-2xl z-30"
          >
            {tree.map((node) =>
              isSection(node) ? (
                <li key={node.id} role="presentation">
                  <div
                    aria-hidden
                    className="px-3.5 pt-3.5 pb-1.5 text-[10px] uppercase tracking-wider text-white/32 font-medium select-none flex items-center gap-1.5"
                  >
                    {node.label}
                    {node.children.some((c) => c.badge) && (
                      <span
                        data-testid="section-badge"
                        aria-label="Attention required"
                        className="text-red-400 text-[10px] normal-case"
                      >
                        !
                      </span>
                    )}
                  </div>
                  {node.children.map((child) => (
                    <LeafRow
                      key={child.id}
                      leaf={child}
                      indented
                      active={child.id === activeId}
                      onClick={() => handleLeafClick(child)}
                    />
                  ))}
                </li>
              ) : (
                <LeafRow
                  key={node.id}
                  leaf={node}
                  indented={false}
                  active={node.id === activeId}
                  onClick={() => handleLeafClick(node)}
                />
              ),
            )}
          </ul>
        </>
      )}
    </div>
  )
}

interface LeafRowProps {
  leaf: NavLeaf
  indented: boolean
  active: boolean
  onClick: () => void
}

function LeafRow({ leaf, indented, active, onClick }: LeafRowProps) {
  return (
    <li
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={[
        'flex items-center gap-2 cursor-pointer border-b border-white/4 last:border-b-0',
        indented ? 'pl-6 pr-3.5 py-2.5 text-[12.5px]' : 'px-3.5 py-2.5 text-[13px]',
        active ? 'text-[#f5c542] bg-[#f5c54214]' : 'text-white/70',
      ].join(' ')}
    >
      <span className="flex-1">{leaf.label}</span>
      {leaf.badge && (
        <span
          data-testid="leaf-badge"
          aria-label="Attention required"
          title="Attention required"
          className="text-red-400 text-[10px]"
        >
          !
        </span>
      )}
    </li>
  )
}
