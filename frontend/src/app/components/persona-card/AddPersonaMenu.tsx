import { useEffect, useRef } from "react"

interface AddPersonaMenuProps {
  onCreateNew: () => void
  onImport: () => void
  onClose: () => void
}

/**
 * Popover menu anchored to the AddPersonaCard. Offers two ways to add a
 * persona: create a blank one (legacy click behaviour) or import from a
 * previously-exported ``.chatsune-persona.tar.gz`` archive.
 */
export function AddPersonaMenu({ onCreateNew, onImport, onClose }: AddPersonaMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Click-outside and Escape close behaviour — mirrors other popover menus
  // (e.g. PersonaItem's context menu) for consistency.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose()
    }
    function onDocClick(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose()
      }
    }
    document.addEventListener("keydown", onKey)
    document.addEventListener("mousedown", onDocClick)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("mousedown", onDocClick)
    }
  }, [onClose])

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label="Add persona options"
      className="absolute left-1/2 top-full z-20 mt-2 flex -translate-x-1/2 flex-col overflow-hidden rounded-lg border border-white/10 bg-elevated shadow-2xl"
      style={{ minWidth: 180 }}
    >
      <button
        type="button"
        role="menuitem"
        onClick={onCreateNew}
        className="px-4 py-2.5 text-left text-[12px] text-white/80 hover:bg-white/6 transition-colors cursor-pointer font-mono uppercase tracking-wider"
      >
        Create new
      </button>
      <div className="h-px bg-white/8" aria-hidden="true" />
      <button
        type="button"
        role="menuitem"
        onClick={onImport}
        className="px-4 py-2.5 text-left text-[12px] text-white/80 hover:bg-white/6 transition-colors cursor-pointer font-mono uppercase tracking-wider"
      >
        Import from file
      </button>
    </div>
  )
}
