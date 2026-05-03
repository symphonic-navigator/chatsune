import { useState, useRef, useEffect } from "react"
import type { DraggableAttributes, DraggableSyntheticListeners } from "@dnd-kit/core"
import type { PersonaDto } from "../../../core/types/persona"
import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra"
import { useMemoryStore } from "../../../core/store/memoryStore"
import type { JournalEntryDto } from "../../../core/api/memory"
import { useViewport } from "../../../core/hooks/useViewport"
import { PINNED_STRIPE_STYLE } from "./pinnedStripe"

type MenuEntry =
  | { divider: true }
  | { label: string; action: () => void }

const EMPTY_ENTRIES: JournalEntryDto[] = []

/** Dot colour matching JournalBadge thresholds */
function memoryDotColour(count: number): string {
  if (count <= 20) return "bg-green-500"
  if (count <= 35) return "bg-yellow-400"
  return "bg-red-500"
}

interface PersonaItemProps {
  persona: PersonaDto
  isActive: boolean
  onSelect: (persona: PersonaDto) => void
  onNewChat: (persona: PersonaDto) => void
  onNewIncognitoChat: (persona: PersonaDto) => void
  onEdit: (persona: PersonaDto) => void
  onPin?: (persona: PersonaDto) => void
  onUnpin?: (persona: PersonaDto) => void
  onOpenOverlay?: () => void
  dragRef?: (node: HTMLElement | null) => void
  dragListeners?: DraggableSyntheticListeners
  dragAttributes?: DraggableAttributes
  isDragging?: boolean
}

export function PersonaItem({
  persona,
  isActive,
  onSelect,
  onNewChat,
  onNewIncognitoChat,
  onEdit,
  onPin,
  onUnpin,
  onOpenOverlay,
  dragRef,
  dragListeners,
  dragAttributes,
  isDragging,
}: PersonaItemProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const { isMobile } = useViewport()

  const uncommitted = useMemoryStore((s) => s.uncommittedEntries[persona.id] ?? EMPTY_ENTRIES)
  const uncommittedCount = uncommitted.length

  const chakra = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour] ?? CHAKRA_PALETTE.solar

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

  // Menu order: New Chat, New Incognito, [divider], Overview, Edit, [divider], Pin/Unpin.
  // Dividers are dropped on mobile to keep the menu compact.
  const divider: MenuEntry = { divider: true }
  const menuItems: MenuEntry[] = [
    { label: "New Chat", action: () => { onNewChat(persona); setMenuOpen(false) } },
    { label: "New Incognito Chat", action: () => { onNewIncognitoChat(persona); setMenuOpen(false) } },
    ...(!isMobile ? [divider] : []),
    ...(onOpenOverlay ? [{ label: "Overview", action: () => { onOpenOverlay(); setMenuOpen(false) } }] : []),
    { label: "Edit", action: () => { onEdit(persona); setMenuOpen(false) } },
    ...(!isMobile && (onPin || onUnpin) ? [divider] : []),
    ...(onPin ? [{ label: "Pin", action: () => { onPin(persona); setMenuOpen(false) } }] : []),
    ...(onUnpin ? [{ label: "Unpin", action: () => { onUnpin(persona); setMenuOpen(false) } }] : []),
  ]

  return (
    <div
      ref={dragRef}
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1.5 transition-colors
        ${isActive ? "bg-white/8" : "hover:bg-white/5"}
        ${isDragging ? "opacity-40" : ""}`}
      style={persona.pinned ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' } : { paddingLeft: '8px', paddingRight: '8px' }}
      onClick={() => onSelect(persona)}
    >
      <span
        aria-label="Drag to reorder"
        title="Drag to reorder"
        className="w-0 overflow-hidden cursor-grab select-none text-[10px] leading-none text-white/15 group-hover:w-auto group-hover:text-white/60 group-focus-within:w-auto group-focus-within:text-white/60 transition-all"
        {...(dragListeners ?? {})}
        {...(dragAttributes ?? {})}
      >
        ⠿
      </span>

      <div
        className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-[9px] font-serif"
        style={{
          background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}10 80%)`,
          color: `${chakra.hex}CC`,
        }}
      >
        {persona.monogram || persona.name.charAt(0).toUpperCase()}
      </div>

      <span
        className={`min-w-0 flex-1 truncate text-[13px] transition-colors
          ${isActive ? "text-white/90" : "text-white/50 group-hover:text-white/75"}`}
      >
        {persona.name}
      </span>

      {uncommittedCount > 0 && (
        <span
          className={`h-2 w-2 flex-shrink-0 rounded-full ${memoryDotColour(uncommittedCount)}`}
          title={`${uncommittedCount} uncommitted memory entries`}
        />
      )}

      {/*
        Right-side affordance. For NSFW personas the resting state shows a
        kissmark (visual NSFW flag, matches NewChatRow precedent); on hover
        it swaps to the "···" context-menu trigger. Non-NSFW personas keep
        the original behaviour: nothing at rest, dots on hover. Both states
        sit in the same fixed-size slot so layout never shifts.
      */}
      <div className="relative flex h-5 w-5 flex-shrink-0 items-center justify-center">
        {persona.nsfw && (
          <span
            aria-label="NSFW"
            title="NSFW"
            className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] opacity-100 transition-opacity group-hover:opacity-0 group-focus-within:opacity-0 [@media(hover:none)]:group-hover:opacity-100"
          >
            💋
          </span>
        )}
        <button
          type="button"
          aria-label="More options"
          title="More options"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className="flex h-5 w-5 items-center justify-center rounded text-sm text-white/60 opacity-0 transition-all hover:bg-white/10 hover:text-white/85 group-hover:opacity-100 focus:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
          onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
        >
          ···
        </button>
      </div>

      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-2 top-8 z-50 w-48 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
          onClick={(e) => e.stopPropagation()}
        >
          {menuItems.map((item, idx) => {
            if ("divider" in item) {
              return <div key={`div-${idx}`} className="h-px bg-white/10 my-1 mx-2" aria-hidden />
            }
            return (
              <button
                key={item.label}
                type="button"
                onClick={item.action}
                className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
              >
                {item.label}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
