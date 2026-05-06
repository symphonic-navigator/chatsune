import { useRef, useState } from "react"
import { useViewport } from "../../../core/hooks/useViewport"
import { PINNED_STRIPE_STYLE } from "./pinnedStripe"
import type { ProjectDto } from "../../../features/projects/types"
import { FloatingMenu } from "../floating/FloatingMenu"

type MenuEntry =
  | { divider: true }
  | { label: string; action: () => void }

interface ProjectSidebarItemProps {
  project: ProjectDto
  /** Open the Project-Detail-Overlay (Phase 9). */
  onOpen: (projectId: string) => void
  /** Open the Project-Detail-Overlay's Overview tab (Phase 9). */
  onEdit: (projectId: string) => void
  /** Open the DeleteProjectModal (Phase 12). */
  onDelete: (projectId: string) => void
  /** Toggle the sidebar pin flag. */
  onTogglePin: (projectId: string, pinned: boolean) => void
}

const LONG_PRESS_MS = 500

/**
 * One row in the sidebar Projects-zone. Mirrors `PersonaItem`'s shape
 * — avatar slot, truncated name, hover-revealed "···" menu — and
 * exposes the same context-menu surface via right-click on desktop and
 * long-press on touch devices. Menu items: Pin/Unpin · Edit · Open ·
 * Delete.
 *
 * The avatar slot here is the project emoji (or a neutral fallback dot)
 * — projects don't carry a chakra colour-scheme.
 */
export function ProjectSidebarItem({
  project,
  onOpen,
  onEdit,
  onDelete,
  onTogglePin,
}: ProjectSidebarItemProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const longPressTimer = useRef<number | null>(null)
  const { isMobile } = useViewport()

  function clearLongPress() {
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current)
      longPressTimer.current = null
    }
  }

  function handleTouchStart() {
    clearLongPress()
    longPressTimer.current = window.setTimeout(() => {
      setMenuOpen(true)
    }, LONG_PRESS_MS)
  }

  // Menu order mirrors spec §6.1: Pin/Unpin · Edit · Delete · Open.
  // "Delete" is grouped at the bottom (separated by a divider on desktop)
  // because it is the destructive action; "Open" sits above it as a
  // benign alias for clicking the row body.
  const divider: MenuEntry = { divider: true }
  const menuItems: MenuEntry[] = [
    {
      label: project.pinned ? "Unpin" : "Pin",
      action: () => {
        onTogglePin(project.id, !project.pinned)
        setMenuOpen(false)
      },
    },
    ...(!isMobile ? [divider] : []),
    {
      label: "Edit",
      action: () => {
        onEdit(project.id)
        setMenuOpen(false)
      },
    },
    {
      label: "Open",
      action: () => {
        onOpen(project.id)
        setMenuOpen(false)
      },
    },
    ...(!isMobile ? [divider] : []),
    {
      label: "Delete",
      action: () => {
        onDelete(project.id)
        setMenuOpen(false)
      },
    },
  ]

  const displayName = project.title || "Untitled project"
  const emoji = project.emoji?.trim() || ""

  return (
    <div
      className="group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1.5 transition-colors hover:bg-white/5"
      style={
        project.pinned
          ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' }
          : { paddingLeft: '8px', paddingRight: '8px' }
      }
      onClick={() => onOpen(project.id)}
      onContextMenu={(e) => {
        e.preventDefault()
        setMenuOpen(true)
      }}
      onTouchStart={handleTouchStart}
      onTouchEnd={clearLongPress}
      onTouchCancel={clearLongPress}
      onTouchMove={clearLongPress}
    >
      <div
        className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-white/5 text-[12px]"
        aria-hidden="true"
      >
        {emoji || <span className="h-1.5 w-1.5 rounded-full bg-white/30" />}
      </div>

      <span className="min-w-0 flex-1 truncate text-[13px] text-white/50 transition-colors group-hover:text-white/75">
        {displayName}
      </span>

      <button
        ref={triggerRef}
        type="button"
        aria-label="More options"
        title="More options"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/60 opacity-0 transition-all hover:bg-white/10 hover:text-white/85 group-hover:opacity-100 focus:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
        onClick={(e) => {
          e.stopPropagation()
          setMenuOpen(true)
        }}
      >
        ···
      </button>

      <FloatingMenu
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        anchorRef={triggerRef}
        width={176}
        role="menu"
      >
        {menuItems.map((item, idx) => {
          if ("divider" in item) {
            return <div key={`div-${idx}`} className="mx-2 my-1 h-px bg-white/10" aria-hidden />
          }
          return (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={item.action}
              className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
            >
              {item.label}
            </button>
          )
        })}
      </FloatingMenu>
    </div>
  )
}
