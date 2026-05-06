import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatApi, type ChatSessionDto } from '../../../core/api/chat'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics, type BaseEvent } from '../../../core/types/events'
import { useProjectsStore } from '../../../features/projects/useProjectsStore'
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
  const [sessions, setSessions] = useState<ChatSessionDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const projects = useProjectsStore((s) => s.projects)
  const [search, setSearch] = useState('')
  const navigate = useNavigate()
  const [searchResults, setSearchResults] = useState<ChatSessionDto[] | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch this persona's full chat history (including project-bound
  // chats). useChatSessions intentionally excludes project chats —
  // see useChatSessions.ts:32-34. We do our own fetch here, mirroring
  // the user-modal HistoryTab's pattern at HistoryTab.tsx:140-142.
  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    chatApi
      .listSessions({ include_project_chats: true })
      .then((res) => {
        if (cancelled) return
        const forPersona = res
          .filter((s) => s.persona_id === persona.id)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        setSessions(forPersona)
      })
      .catch(() => {
        // Empty list on failure — matches useChatSessions's silent-fail style.
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [persona.id])

  // Live update on delete: when any session for this persona is
  // deleted, drop it from the local list. This pairs with the new
  // reactive listener in ChatView (Task 1) so the persona-overlay
  // HistoryTab does not show stale rows.
  useEffect(() => {
    const unsub = eventBus.on(Topics.CHAT_SESSION_DELETED, (event: BaseEvent) => {
      const sessionId = event.payload.session_id as string
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
    })
    return unsub
  }, [])

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)

    const trimmed = search.trim()
    if (!trimmed) {
      setSearchResults(null)
      setIsSearching(false)
      return
    }

    setIsSearching(true)
    searchTimer.current = setTimeout(async () => {
      try {
        const results = await chatApi.searchSessions({
          q: trimmed,
          persona_id: persona.id,
        })
        setSearchResults(results)
      } catch {
        setSearchResults([])
      } finally {
        setIsSearching(false)
      }
    }, 300)

    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current)
    }
  }, [search, persona.id])

  const filtered = useMemo(() => {
    if (searchResults !== null) {
      return searchResults
    }
    return sessions
  }, [sessions, searchResults])

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
          className="w-full bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/60 outline-none transition-colors font-mono"
          style={{ borderColor: search ? `${chakra.hex}40` : undefined }}
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {(isLoading || isSearching) && (
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">
            {isSearching ? 'Searching...' : 'Loading...'}
          </p>
        )}
        {!isLoading && filtered.length === 0 && (
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">No sessions found.</p>
        )}
        {grouped.map(([group, groupSessions]) => (
          <div key={group}>
            <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-widest text-white/60 font-mono">
              {group}
            </div>
            {groupSessions.map((s) => {
              const project = s.project_id ? projects[s.project_id] ?? null : null
              return (
                <SessionRow
                  key={s.id}
                  session={s}
                  chakra={chakra}
                  onOpen={() => handleOpen(s)}
                  projectPill={project ? { emoji: project.emoji, title: project.title } : null}
                />
              )
            })}
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
  projectPill: { emoji: string | null; title: string } | null
}

function SessionRow({ session, chakra, onOpen, projectPill }: SessionRowProps) {
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genSuccess, setGenSuccess] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const [genError, setGenError] = useState(false)
  const deleteTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    setGenError(false)
    setGenerating(true)
    try {
      await chatApi.generateTitle(session.id)
    } catch {
      // Title arrives via event
    }
  }, [session.id])

  // Reset GEN button when title arrives
  useEffect(() => {
    if (!generating) return
    setGenerating(false)
    setGenSuccess(true)
    const t = setTimeout(() => setGenSuccess(false), 1000)
    return () => clearTimeout(t)
  }, [session.title])

  // Fallback: reset after 10s if no title event arrives, surface an error notice
  useEffect(() => {
    if (!generating) return
    const t = setTimeout(() => {
      setGenerating(false)
      setGenError(true)
    }, 10000)
    return () => clearTimeout(t)
  }, [generating])

  // Auto-clear error notice after a few seconds
  useEffect(() => {
    if (!genError) return
    const t = setTimeout(() => setGenError(false), 4000)
    return () => clearTimeout(t)
  }, [genError])

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
    <div className="group rounded-lg transition-colors hover:bg-white/4 focus-within:bg-white/4">
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
              <>
                <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
                  {session.title ?? formatDate(session.updated_at)}
                </p>
                {projectPill && (
                  <span
                    data-testid="history-project-pill"
                    className="ml-1 flex-shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] text-white/65"
                    style={{ background: 'rgba(255,255,255,0.05)' }}
                  >
                    {projectPill.emoji ?? '—'} {projectPill.title}
                  </span>
                )}
              </>
            )}
          </div>
          <p className="text-[10px] text-white/60 font-mono mt-0.5">
            {formatDate(session.updated_at)}
          </p>
        </button>

        {/* Actions */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 focus-within:opacity-100 transition-opacity flex-shrink-0">
          <button type="button" onClick={startEdit} title="Rename session" aria-label="Rename session" className={BTN_NEUTRAL}>
            REN
          </button>
          <button
            type="button"
            onClick={handleGenerateTitle}
            disabled={generating}
            title="Regenerate title"
            aria-label="Regenerate session title"
            className={`${BTN_NEUTRAL} ${generating ? 'opacity-60 cursor-not-allowed' : ''} ${genSuccess ? 'text-gold' : ''}`}
          >
            {generating ? (
              <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-white/20 border-t-white/50" />
            ) : genSuccess ? 'OK' : 'GEN'}
          </button>
          {confirmDelete ? (
            <button
              type="button"
              onClick={handleDelete}
              title="Confirm delete (click again)"
              aria-label="Confirm delete session (click again)"
              className={BTN_RED}
            >
              SURE?
            </button>
          ) : (
            <button
              type="button"
              onClick={startDeleteConfirm}
              title="Delete session"
              aria-label="Delete session"
              className={BTN_NEUTRAL}
            >
              DEL
            </button>
          )}
        </div>
        <span className="sr-only" aria-live="polite">
          {confirmDelete ? 'Confirm deletion: press SURE to delete this session.' : ''}
          {genError ? 'Title generation failed, please retry.' : ''}
        </span>

        {/* Open arrow */}
        <span
          className="text-[11px] text-white/60 transition-colors flex-shrink-0 cursor-pointer"
          aria-hidden="true"
          onMouseEnter={(e) => { e.currentTarget.style.color = `${chakra.hex}80` }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
          onClick={onOpen}
        >
          ›
        </span>
      </div>
      {genError && (
        <p className="px-3 pb-2 text-[11px] text-red-400/90 font-mono">
          Title generation failed, please retry.
        </p>
      )}
    </div>
  )
}
