import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatApi, type ChatSessionDto } from '../../../core/api/chat'
import { useChatSessions } from '../../../core/hooks/useChatSessions'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'

interface HistoryTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onClose: () => void
}

function getDateGroup(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const today = now.toDateString()
  const yesterday = new Date(now.getTime() - 86_400_000).toDateString()
  const weekAgo = new Date(now.getTime() - 7 * 86_400_000)
  const monthAgo = new Date(now.getTime() - 30 * 86_400_000)

  if (date.toDateString() === today) return 'Today'
  if (date.toDateString() === yesterday) return 'Yesterday'
  if (date > weekAgo) return 'This Week'
  if (date > monthAgo) return 'This Month'
  return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

function groupSessions(sessions: ChatSessionDto[]): [string, ChatSessionDto[]][] {
  const map = new Map<string, ChatSessionDto[]>()
  for (const s of sessions) {
    const group = getDateGroup(s.updated_at)
    const existing = map.get(group) ?? []
    map.set(group, [...existing, s])
  }
  return Array.from(map.entries())
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

export function HistoryTab({ persona, chakra, onClose }: HistoryTabProps) {
  const { sessions, isLoading } = useChatSessions()
  const [search, setSearch] = useState('')
  const navigate = useNavigate()

  const filtered = useMemo(() => {
    let result = sessions.filter((s) => s.persona_id === persona.id)

    if (search.trim()) {
      const term = search.toLowerCase()
      result = result.filter((s) => {
        const title = s.title ?? ''
        return title.toLowerCase().includes(term) || s.id.toLowerCase().includes(term)
      })
    }

    return result
  }, [sessions, search, persona.id])

  const grouped = useMemo(() => groupSessions(filtered), [filtered])

  function handleOpen(session: ChatSessionDto) {
    navigate(`/chat/${session.persona_id}/${session.id}`)
    onClose()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search history..."
          aria-label="Search session history"
          className="w-full bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none transition-colors font-mono"
          style={{ borderColor: search ? `${chakra.hex}40` : undefined }}
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {isLoading && (
          <p className="px-4 py-3 text-[12px] text-white/30 font-mono">Loading...</p>
        )}
        {!isLoading && filtered.length === 0 && (
          <p className="px-4 py-3 text-[12px] text-white/30 font-mono">No sessions found.</p>
        )}
        {grouped.map(([group, groupSessions]) => (
          <div key={group}>
            <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-widest text-white/30 font-mono">
              {group}
            </div>
            {groupSessions.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                chakra={chakra}
                onOpen={() => handleOpen(s)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}


interface SessionRowProps {
  session: ChatSessionDto
  chakra: ChakraPaletteEntry
  onOpen: () => void
}

function SessionRow({ session, chakra, onOpen }: SessionRowProps) {
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [generating, setGenerating] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const deleteTimer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  useEffect(() => {
    return () => {
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
    }
  }, [])

  const startEdit = useCallback(() => {
    setEditValue(session.title ?? '')
    setEditing(true)
  }, [session.title])

  const cancelEdit = useCallback(() => {
    setEditing(false)
    setEditValue('')
  }, [])

  const saveEdit = useCallback(async () => {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === session.title) {
      cancelEdit()
      return
    }
    try {
      await chatApi.updateSession(session.id, { title: trimmed })
    } catch {
      // Title update arrives via event
    }
    setEditing(false)
  }, [editValue, session.id, session.title, cancelEdit])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveEdit()
    if (e.key === 'Escape') cancelEdit()
  }, [saveEdit, cancelEdit])

  const handleGenerateTitle = useCallback(async () => {
    setGenerating(true)
    try {
      await chatApi.generateTitle(session.id)
    } catch {
      // Title arrives via event
    } finally {
      setTimeout(() => setGenerating(false), 2000)
    }
  }, [session.id])

  const handleDelete = useCallback(async () => {
    try {
      await chatApi.deleteSession(session.id)
    } catch {
      // Removal via event
    }
    setConfirmDelete(false)
  }, [session.id])

  const startDeleteConfirm = useCallback(() => {
    if (deleteTimer.current) clearTimeout(deleteTimer.current)
    setConfirmDelete(true)
    deleteTimer.current = setTimeout(() => setConfirmDelete(false), 3000)
  }, [])

  return (
    <div className="group rounded-lg transition-colors hover:bg-white/4">
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Main content */}
        <button
          type="button"
          onClick={onOpen}
          className="flex-1 min-w-0 text-left"
        >
          <div className="flex items-center gap-2">
            {editing ? (
              <input
                ref={inputRef}
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={handleKeyDown}
                onBlur={saveEdit}
                onClick={(e) => e.stopPropagation()}
                className="flex-1 bg-white/[0.04] border rounded px-2 py-0.5 text-[13px] text-white/80 outline-none font-mono"
                style={{ borderColor: `${chakra.hex}40` }}
              />
            ) : (
              <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
                {session.title ?? formatDate(session.updated_at)}
              </p>
            )}
          </div>
          <p className="text-[10px] text-white/30 font-mono mt-0.5">
            {formatDate(session.updated_at)}
          </p>
        </button>

        {/* Actions */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button type="button" onClick={startEdit} title="Rename" className={BTN_NEUTRAL}>
            REN
          </button>
          <button
            type="button"
            onClick={handleGenerateTitle}
            disabled={generating}
            title="Generate title"
            className={`${BTN_NEUTRAL} ${generating ? 'opacity-30 cursor-not-allowed' : ''}`}
          >
            {generating ? '...' : 'GEN'}
          </button>
          {confirmDelete ? (
            <button type="button" onClick={handleDelete} className={BTN_RED}>
              SURE?
            </button>
          ) : (
            <button type="button" onClick={startDeleteConfirm} className={BTN_NEUTRAL}>
              DEL
            </button>
          )}
        </div>

        {/* Open arrow */}
        <span
          className="text-[11px] text-white/20 transition-colors flex-shrink-0 cursor-pointer"
          style={{ color: undefined }}
          onMouseEnter={(e) => { e.currentTarget.style.color = `${chakra.hex}80` }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.2)' }}
          onClick={onOpen}
        >
          ›
        </span>
      </div>
    </div>
  )
}
