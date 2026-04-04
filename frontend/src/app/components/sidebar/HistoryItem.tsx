import { useState, useRef, useEffect } from "react"
import type { ChatSessionDto } from "../../../core/api/chat"

function formatSessionDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString("de-DE", {
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
  onClick: (session: ChatSessionDto) => void
  onDelete: (session: ChatSessionDto) => void
}

export function HistoryItem({ session, isPinned, isActive, onClick, onDelete }: HistoryItemProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

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
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1 text-[12px] transition-colors
        ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}`}
      onClick={() => onClick(session)}
    >
      {isPinned && <span className="flex-shrink-0 text-[11px]">📌</span>}
      <div className="flex flex-1 flex-col gap-0.5 overflow-hidden">
        <span className="truncate text-[13px]">
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
