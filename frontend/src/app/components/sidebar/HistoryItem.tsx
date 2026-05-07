import { useState, useRef, useEffect } from "react"
import { useLocation } from "react-router-dom"
import type { ChatSessionDto } from "../../../core/api/chat"
import type { ChakraColour } from "../../../core/types/chakra"
import { CHAKRA_PALETTE } from "../../../core/types/chakra"
import { PINNED_STRIPE_STYLE } from "./pinnedStripe"
import { FloatingMenu } from "../floating/FloatingMenu"
import { StreamingIndicatorDot } from "../../../features/chat/StreamingIndicatorDot"
import { useChatStore } from "../../../core/store/chatStore"
import { sendMessage } from "../../../core/websocket/connection"

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
  onRename?: (session: ChatSessionDto, title: string) => void
}

export function HistoryItem({ session, isPinned, isActive, monogram, colourScheme, onClick, onDelete, onTogglePin, onRename }: HistoryItemProps) {
  const chakra = colourScheme ? CHAKRA_PALETTE[colourScheme] : null
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const triggerRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const location = useLocation()

  // Subscribe to this session's streaming slot so the right-click "Stop
  // generation" entry appears when an inference is in flight here. The
  // dot itself subscribes independently via StreamingIndicatorDot.
  const isStreamingHere = useChatStore((s) =>
    Boolean(s.streamsBySession.get(session.id)?.isStreaming),
  )

  // Close menu and reset edit state on route change
  useEffect(() => {
    setMenuOpen(false)
    setConfirmDelete(false)
    setEditing(false)
  }, [location])

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [editing])

  const startRename = () => {
    setEditValue(session.title ?? '')
    setEditing(true)
    setMenuOpen(false)
  }

  const commitRename = () => {
    const trimmed = editValue.trim()
    if (!trimmed) {
      setEditing(false)
      return
    }
    onRename?.(session, trimmed)
    setEditing(false)
  }

  const cancelRename = () => {
    setEditing(false)
  }

  return (
    <div
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1 text-[12px] transition-colors
        ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}`}
      style={isPinned ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' } : { paddingLeft: '8px', paddingRight: '8px' }}
      onClick={() => onClick(session)}
      onContextMenu={(e) => {
        // Right-click opens the same FloatingMenu used by the "···"
        // affordance, so the Stop-generation entry surfaces without
        // having to hover and aim. Anchored at the trigger button.
        e.preventDefault()
        setMenuOpen(true)
      }}
    >
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
        {editing ? (
          <input
            ref={inputRef}
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                commitRename()
              } else if (e.key === 'Escape') {
                e.preventDefault()
                cancelRename()
              }
            }}
            onBlur={commitRename}
            onClick={(e) => e.stopPropagation()}
            className="w-full rounded border border-white/15 bg-black/30 px-1 py-0 text-[13px] text-white/90 outline-none focus:border-white/30"
          />
        ) : (
          <span className="flex min-w-0 items-center gap-1.5 truncate text-[13px]" title={session.title ?? undefined}>
            <StreamingIndicatorDot sessionId={session.id} />
            <span className="truncate">{session.title ?? formatSessionDate(session.updated_at)}</span>
          </span>
        )}
        {!editing && session.title && (
          <span className="truncate text-[11px] opacity-50">
            {formatSessionDate(session.updated_at)}
          </span>
        )}
      </div>

      <button
        ref={triggerRef}
        type="button"
        aria-label="More options"
        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/30 opacity-0 transition-all hover:bg-white/10 hover:text-white/70 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
        onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
      >
        ···
      </button>

      <FloatingMenu
        open={menuOpen}
        onClose={() => {
          setMenuOpen(false)
          setConfirmDelete(false)
        }}
        anchorRef={triggerRef}
        width={160}
      >
        {/* Stop generation — only when an inference is streaming for this session */}
        {isStreamingHere && (
          <button
            type="button"
            onClick={() => {
              const correlationId = useChatStore.getState()
                .streamsBySession.get(session.id)?.correlationId
              if (correlationId) {
                sendMessage({ type: 'chat.cancel', correlation_id: correlationId })
              }
              setMenuOpen(false)
            }}
            className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
          >
            Stop generation
          </button>
        )}

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

        {/* Rename */}
        {onRename && (
          <button
            type="button"
            onClick={startRename}
            className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
          >
            Rename
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
      </FloatingMenu>
    </div>
  )
}
