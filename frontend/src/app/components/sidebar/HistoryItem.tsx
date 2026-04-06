import { useState, useRef, useEffect } from "react"
import { useLocation } from "react-router-dom"
import type { DraggableAttributes, DraggableSyntheticListeners } from "@dnd-kit/core"
import type { ChatSessionDto } from "../../../core/api/chat"
import type { ChakraColour } from "../../../core/types/chakra"
import { CHAKRA_PALETTE } from "../../../core/types/chakra"

function formatSessionDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface HistoryItemProps {
  session: ChatSessionDto
  isPinned: boolean
  isActive: boolean
  monogram?: string
  colourScheme?: ChakraColour
  onClick: (session: ChatSessionDto) => void
  onDelete: (session: ChatSessionDto) => void
  onTogglePin?: (session: ChatSessionDto, pinned: boolean) => void
  dragListeners?: DraggableSyntheticListeners
  dragAttributes?: DraggableAttributes
  isDragging?: boolean
}

export function HistoryItem({ session, isPinned, isActive, monogram, colourScheme, onClick, onDelete, onTogglePin, dragListeners, dragAttributes, isDragging }: HistoryItemProps) {
  const chakra = colourScheme ? CHAKRA_PALETTE[colourScheme] : null
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const location = useLocation()

  // Close menu on route change
  useEffect(() => {
    setMenuOpen(false)
    setConfirmDelete(false)
  }, [location])

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
        setConfirmDelete(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen])

  return (
    <div
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-[12px] transition-colors
        ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}
        ${isDragging ? "opacity-40" : ""}`}
      onClick={() => onClick(session)}
    >
      {/* Drag handle — only visible on hover */}
      {dragListeners && (
        <span
          className="w-0 overflow-hidden cursor-grab select-none text-[10px] leading-none text-white/15 group-hover:w-auto group-hover:text-white/30 transition-all"
          {...(dragListeners ?? {})}
          {...(dragAttributes ?? {})}
          onClick={(e) => e.stopPropagation()}
        >
          ⠿
        </span>
      )}

      {chakra && monogram && (
        <div
          className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[8px] font-serif"
          style={{
            background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}10 80%)`,
            color: `${chakra.hex}CC`,
          }}
        >
          {monogram}
        </div>
      )}
      <div className="flex flex-1 flex-col gap-0.5 overflow-hidden">
        <span className="truncate text-[13px]" title={session.title ?? undefined}>
          {session.title ?? formatSessionDate(session.updated_at)}
        </span>
        {session.title && (
          <span className="truncate text-[11px] opacity-50">
            {formatSessionDate(session.updated_at)}
          </span>
        )}
      </div>

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
          className="absolute right-2 top-8 z-50 w-40 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Pin / Unpin */}
          {onTogglePin && (
            <button
              type="button"
              onClick={() => {
                onTogglePin(session, !isPinned)
                setMenuOpen(false)
              }}
              className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
            >
              {isPinned ? "Unpin" : "Pin"}
            </button>
          )}

          {/* Delete */}
          {confirmDelete ? (
            <button
              type="button"
              onClick={() => {
                onDelete(session)
                setMenuOpen(false)
                setConfirmDelete(false)
              }}
              className="w-full px-3 py-1.5 text-left text-[13px] text-red-400 transition-colors hover:bg-red-400/10"
            >
              Confirm delete?
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
            >
              Delete
            </button>
          )}
        </div>
      )}
    </div>
  )
}
