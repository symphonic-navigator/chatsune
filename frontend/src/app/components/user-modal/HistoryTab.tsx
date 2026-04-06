import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatApi, type ChatSessionDto } from '../../../core/api/chat'
import { useChatSessions } from '../../../core/hooks/useChatSessions'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE, type ChakraColour } from '../../../core/types/chakra'

interface HistoryTabProps {
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

export function HistoryTab({ onClose }: HistoryTabProps) {
  const { sessions, isLoading } = useChatSessions()
  const { personas } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const [search, setSearch] = useState('')
  const [personaFilter, setPersonaFilter] = useState<string>('all')
  const navigate = useNavigate()

  // Sanitised mode: build set of NSFW persona IDs
  const nsfwPersonaIds = useMemo(
    () => new Set(personas.filter((p) => p.nsfw).map((p) => p.id)),
    [personas],
  )

  // Filter sessions by sanitised mode, persona filter, and search
  const filtered = useMemo(() => {
    let result = sessions

    // Sanitised mode
    if (isSanitised) {
      result = result.filter((s) => !nsfwPersonaIds.has(s.persona_id))
    }

    // Persona filter
    if (personaFilter !== 'all') {
      result = result.filter((s) => s.persona_id === personaFilter)
    }

    // Text search
    if (search.trim()) {
      const term = search.toLowerCase()
      result = result.filter((s) => {
        const name = personas.find((p) => p.id === s.persona_id)?.name ?? s.persona_id
        const title = s.title ?? ''
        return (
          name.toLowerCase().includes(term) ||
          title.toLowerCase().includes(term) ||
          s.id.toLowerCase().includes(term)
        )
      })
    }

    return result
  }, [sessions, search, personas, personaFilter, isSanitised, nsfwPersonaIds])

  // Personas available for the filter dropdown (only those with sessions, respecting sanitised mode)
  const filterPersonas = useMemo(() => {
    const personaIdsWithSessions = new Set(sessions.map((s) => s.persona_id))
    return personas
      .filter((p) => personaIdsWithSessions.has(p.id))
      .filter((p) => !isSanitised || !p.nsfw)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [personas, sessions, isSanitised])

  const grouped = useMemo(() => groupSessions(filtered), [filtered])

  function handleOpen(session: ChatSessionDto) {
    navigate(`/chat/${session.persona_id}/${session.id}`)
    onClose()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search history..."
          aria-label="Search session history"
          className="flex-1 bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none focus:border-gold/30 transition-colors font-mono"
        />
        <select
          value={personaFilter}
          onChange={(e) => setPersonaFilter(e.target.value)}
          aria-label="Filter by persona"
          className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
          style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 12 12%27%3E%3Cpath d=%27M3 5l3 3 3-3%27 fill=%27none%27 stroke=%27rgba(255,255,255,0.3)%27 stroke-width=%271.5%27/%3E%3C/svg%3E")', backgroundRepeat: 'no-repeat', backgroundPosition: 'right 6px center' }}
        >
          <option value="all">All Personas</option>
          {filterPersonas.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
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
            {groupSessions.map((s) => {
              const persona = personas.find((p) => p.id === s.persona_id)
              return (
                <SessionRow
                  key={s.id}
                  session={s}
                  personaName={persona?.name ?? s.persona_id}
                  monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                  colourScheme={persona?.colour_scheme}
                  onOpen={() => handleOpen(s)}
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
  personaName: string
  monogram?: string
  colourScheme?: ChakraColour
  onOpen: () => void
}

function SessionRow({ session, personaName, monogram, colourScheme, onOpen }: SessionRowProps) {
  const chakra = colourScheme ? CHAKRA_PALETTE[colourScheme] : null
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genSuccess, setGenSuccess] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const sureRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  // Dismiss delete confirmation on outside click
  useEffect(() => {
    if (!confirmDelete) return
    const handleMouseDown = (e: MouseEvent) => {
      if (sureRef.current && !sureRef.current.contains(e.target as Node)) {
        setConfirmDelete(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [confirmDelete])

  // Reset GEN button when title arrives
  useEffect(() => {
    if (!generating) return
    setGenerating(false)
    setGenSuccess(true)
    const t = setTimeout(() => setGenSuccess(false), 1000)
    return () => clearTimeout(t)
  }, [session.title])

  // Fallback: reset after 10s if no title event arrives
  useEffect(() => {
    if (!generating) return
    const t = setTimeout(() => setGenerating(false), 10000)
    return () => clearTimeout(t)
  }, [generating])

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
      // Title update arrives via event; error is non-critical
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
    setConfirmDelete(true)
  }, [])

  return (
    <div className="group rounded-lg transition-colors hover:bg-white/4">
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Persona monogram */}
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

        {/* Main content — clickable to open chat */}
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
                className="flex-1 bg-white/[0.04] border border-gold/30 rounded px-2 py-0.5 text-[13px] text-white/80 outline-none font-mono"
              />
            ) : (
              <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
                {session.title ?? formatDate(session.updated_at)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[10px] text-white/40 font-mono truncate">
              {personaName}
            </p>
            <span className="text-[10px] text-white/20">·</span>
            <p className="text-[10px] text-white/30 font-mono">
              {formatDate(session.updated_at)}
            </p>
          </div>
        </button>

        {/* Actions — visible on hover */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            type="button"
            onClick={startEdit}
            title="Rename"
            className={BTN_NEUTRAL}
          >
            REN
          </button>
          <button
            type="button"
            onClick={handleGenerateTitle}
            disabled={generating}
            title="Generate title"
            className={`${BTN_NEUTRAL} ${generating ? 'opacity-60 cursor-not-allowed' : ''} ${genSuccess ? 'text-gold' : ''}`}
          >
            {generating ? (
              <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-white/20 border-t-white/50" />
            ) : genSuccess ? 'OK' : 'GEN'}
          </button>
          {confirmDelete ? (
            <button ref={sureRef} type="button" onClick={handleDelete} className={BTN_RED}>
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
          className="text-[11px] text-white/20 group-hover:text-gold/50 transition-colors flex-shrink-0 cursor-pointer"
          onClick={onOpen}
        >
          ›
        </span>
      </div>
    </div>
  )
}
