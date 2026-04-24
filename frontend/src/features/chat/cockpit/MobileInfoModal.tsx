import { useState } from 'react'
import type { ReactNode } from 'react'

type Section = {
  id: 'thinking' | 'tools' | 'integrations' | 'voice' | 'live'
  icon: string
  title: string
  statusLine: string
  active: boolean
  body: ReactNode
}

type Props = {
  open: boolean
  onClose: () => void
  sections: Section[]
}

export function MobileInfoModal({ open, onClose, sections }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>(
    () => Object.fromEntries(sections.filter((s) => s.active).map((s) => [s.id, true])),
  )
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-end"
      onClick={onClose}
    >
      <div
        className="w-full max-h-[80vh] overflow-y-auto bg-[#0f0d16] rounded-t-xl border-t border-white/10 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[11px] uppercase tracking-[0.1em] text-white/50 mb-3">
          Cockpit status
        </div>
        {sections.map((s) => {
          const isOpen = !!expanded[s.id]
          const toggle = () => setExpanded((e) => ({ ...e, [s.id]: !isOpen }))
          return (
            <div
              key={s.id}
              role="button"
              tabIndex={0}
              aria-expanded={isOpen}
              onClick={toggle}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggle()
                }
              }}
              className="border-b border-white/5 py-2.5 cursor-pointer select-none"
            >
              <div className="w-full flex justify-between items-center text-sm">
                <span className={s.active ? 'text-white/90' : 'text-white/70'}>
                  {s.icon} {s.title}
                </span>
                <span className="text-xs text-white/50">
                  {s.statusLine} {isOpen ? '▴' : '▾'}
                </span>
              </div>
              {isOpen && <div className="mt-2 pl-1 text-xs text-white/75">{s.body}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
