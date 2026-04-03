import { useState, useRef, useEffect } from "react"
import type { PersonaDto } from "../../../core/types/persona"
import { personaGradient, personaInitial } from "./personaColour"

interface PersonaItemProps {
  persona: PersonaDto
  isActive: boolean
  onSelect: (persona: PersonaDto) => void
  onNewChat: (persona: PersonaDto) => void
  onNewIncognitoChat: (persona: PersonaDto) => void
  onEdit: (persona: PersonaDto) => void
  onUnpin?: (persona: PersonaDto) => void
}

export function PersonaItem({
  persona,
  isActive,
  onSelect,
  onNewChat,
  onNewIncognitoChat,
  onEdit,
  onUnpin,
}: PersonaItemProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen])

  const menuItems = [
    { label: "New Chat", action: () => { onNewChat(persona); setMenuOpen(false) } },
    { label: "New Incognito Chat", action: () => { onNewIncognitoChat(persona); setMenuOpen(false) } },
    { label: "Edit", action: () => { onEdit(persona); setMenuOpen(false) } },
    ...(onUnpin ? [{ label: "Unpin", action: () => { onUnpin(persona); setMenuOpen(false) }, muted: true }] : []),
  ]

  return (
    <div
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 transition-colors
        ${isActive ? "bg-white/8" : "hover:bg-white/5"}`}
      onClick={() => onSelect(persona)}
    >
      <span className="cursor-grab select-none text-[10px] leading-none text-white/15 group-hover:text-white/30">
        ⠿
      </span>

      <div
        className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
        style={{ background: personaGradient(persona) }}
      >
        {personaInitial(persona)}
      </div>

      <span
        className={`flex-1 truncate text-[13px] transition-colors
          ${isActive ? "text-white/90" : "text-white/50 group-hover:text-white/75"}`}
      >
        {persona.name}
      </span>

      <button
        type="button"
        aria-label="More options"
        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/30 opacity-0 transition-all hover:bg-white/10 hover:text-white/70 group-hover:opacity-100"
        onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
      >
        ···
      </button>

      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-2 top-8 z-50 w-48 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
          onClick={(e) => e.stopPropagation()}
        >
          {menuItems.map(({ label, action, muted }) => (
            <button
              key={label}
              type="button"
              onClick={action}
              className={`w-full px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-white/6
                ${muted ? "text-white/40" : "text-white/70"}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
