import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { resolveCrumb } from './resolveCrumb'
import { isSection, type NavLeaf, type NavNode } from './types'

const EN_DASH = '–'
const DEFAULT_ACCENT = '#f5c542'

function accentBackground(colour: string): string {
  // ~8% opacity over the panel background. Hex+alpha is widely supported.
  return colour + '14'
}

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

  const listboxRef = useRef<HTMLUListElement>(null)

  // Flat list of clickable leaf ids in render order — used for ArrowUp / ArrowDown.
  const orderedLeafIds = useMemo(() => {
    const ids: string[] = []
    for (const node of tree) {
      if (isSection(node)) {
        for (const child of node.children) ids.push(child.id)
      } else {
        ids.push(node.id)
      }
    }
    return ids
  }, [tree])

  // On open: focus the active option and scroll it into view.
  useEffect(() => {
    if (!open) return
    const root = listboxRef.current
    if (!root) return
    const activeEl =
      root.querySelector<HTMLElement>(`[data-leaf-id="${activeId}"]`) ??
      root.querySelector<HTMLElement>('[role="option"]')
    if (activeEl) {
      activeEl.focus()
      activeEl.scrollIntoView({ block: 'nearest' })
    }
  }, [open, activeId])

  function moveFocus(delta: 1 | -1) {
    const root = listboxRef.current
    if (!root) return
    const focused = document.activeElement as HTMLElement | null
    const currentId = focused?.getAttribute('data-leaf-id') ?? activeId
    const idx = orderedLeafIds.indexOf(currentId)
    const nextIdx = Math.max(0, Math.min(orderedLeafIds.length - 1, idx + delta))
    const nextId = orderedLeafIds[nextIdx]
    const next = root.querySelector<HTMLElement>(`[data-leaf-id="${nextId}"]`)
    next?.focus()
  }

  function handleListboxKeyDown(e: React.KeyboardEvent<HTMLUListElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveFocus(1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveFocus(-1)
    } else if (e.key === 'Enter' || e.key === ' ') {
      const focused = document.activeElement as HTMLElement | null
      const id = focused?.getAttribute('data-leaf-id')
      if (id) {
        e.preventDefault()
        onSelect(id)
        setOpen(false)
      }
    }
  }

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

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        style={open ? { borderColor: accentColour } : undefined}
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
        <span
          className="text-[14px]"
          style={{ color: open ? accentColour : 'rgba(255,255,255,0.5)' }}
          aria-hidden
        >
          {open ? '▴' : '▾'}
        </span>
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
            ref={listboxRef}
            role="listbox"
            onKeyDown={handleListboxKeyDown}
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
                      accentColour={accentColour}
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
                  accentColour={accentColour}
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
  accentColour: string
  onClick: () => void
}

function LeafRow({ leaf, indented, active, accentColour, onClick }: LeafRowProps) {
  return (
    <li
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      data-leaf-id={leaf.id}
      onClick={onClick}
      style={
        active
          ? { color: accentColour, backgroundColor: accentBackground(accentColour) }
          : undefined
      }
      className={[
        'flex items-center gap-2 cursor-pointer border-b border-white/4 last:border-b-0 outline-none focus:bg-white/8',
        indented ? 'pl-6 pr-3.5 py-2.5 text-[12.5px]' : 'px-3.5 py-2.5 text-[13px]',
        active ? '' : 'text-white/70',
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
