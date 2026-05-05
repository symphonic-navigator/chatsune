import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatApi, type ChatSessionDto } from '../../../core/api/chat'
import { useChatSessions } from '../../../core/hooks/useChatSessions'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useDrawerStore } from '../../../core/store/drawerStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { useProjectsStore } from '../../../features/projects/useProjectsStore'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'
import type { BaseEvent } from '../../../core/types/events'
import { safeLocalStorage } from '../../../core/utils/safeStorage'
import { CHAKRA_PALETTE, type ChakraColour } from '../../../core/types/chakra'
import { PINNED_STRIPE_STYLE } from '../sidebar/pinnedStripe'

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

const INCLUDE_PROJECT_CHATS_KEY = 'chatsune.history.includeProjectChats'

function readIncludeProjectChats(): boolean {
  return safeLocalStorage.getItem(INCLUDE_PROJECT_CHATS_KEY) === 'true'
}

interface HistoryTabProps {
  onClose: () => void
  /**
   * Mindspace: when set, the tab scopes to a single project's chat
   * sessions. Hides the "Include project chats" toggle (it is
   * meaningless in single-project mode). Phase 9 / spec §6.5 Tab 3.
   */
  projectFilter?: string
}

// Parse a backend timestamp into a ``Date`` anchored to UTC. The
// backend stamps ``updated_at`` / ``created_at`` from
// ``datetime.now(UTC)`` but Motor returns naive datetimes (no
// ``tz_aware=True`` on the client) and Pydantic v2 then serialises
// those without a ``Z`` suffix — so the wire string can be
// ``2026-05-05T02:39:00`` rather than ``...Z``. JavaScript treats an
// un-suffixed ISO string as the browser's local time, which would
// shift every history row by the local UTC offset. Appending ``Z``
// when the string carries no offset marker keeps the rendered time
// in sync with the user's wall clock regardless of how the backend
// happens to serialise the field.
function parseTimestamp(isoString: string): Date {
  const hasOffset = /[zZ]|[+-]\d{2}:?\d{2}$/.test(isoString)
  return new Date(hasOffset ? isoString : `${isoString}Z`)
}

function getDateGroup(isoString: string): string {
  const date = parseTimestamp(isoString)
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

// Render a backend timestamp in the browser's local time. ``undefined``
// locale follows the user's browser preference; the absence of a
// ``timeZone`` option means local time is used. ``parseTimestamp``
// anchors the date to UTC so the local conversion is correct even
// when the wire string lacks an offset marker.
function formatDate(isoString: string): string {
  return parseTimestamp(isoString).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

export function HistoryTab({ onClose, projectFilter }: HistoryTabProps) {
  const { sessions: defaultSessions, isLoading: defaultLoading } = useChatSessions()
  const { personas } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const projects = useProjectsStore((s) => s.projects)
  const [search, setSearch] = useState('')
  const [personaFilter, setPersonaFilter] = useState<string>('all')
  const [searchResults, setSearchResults] = useState<ChatSessionDto[] | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()

  // Sanitised mode: build set of NSFW persona IDs
  const nsfwPersonaIds = useMemo(
    () => new Set(personas.filter((p) => p.nsfw).map((p) => p.id)),
    [personas],
  )

  // Mindspace: Phase 9. The "Include project chats" toggle lives on
  // the global UserModal context only (`projectFilter === undefined`).
  // The single-project context already implies "yes, project chats".
  const [includeProjectChats, setIncludeProjectChats] = useState<boolean>(() =>
    readIncludeProjectChats(),
  )
  useEffect(() => {
    safeLocalStorage.setItem(
      INCLUDE_PROJECT_CHATS_KEY,
      includeProjectChats ? 'true' : 'false',
    )
  }, [includeProjectChats])

  // When ``projectFilter`` is set we fetch a project-scoped list. When
  // ``includeProjectChats`` is set without a filter, we fetch the
  // full list (default ``useChatSessions`` excludes project-bound
  // sessions). Otherwise we reuse ``useChatSessions`` so the tab keeps
  // the live event-bus subscriptions a hand-rolled fetch would miss.
  const useFallback = !projectFilter && !includeProjectChats
  const [extraSessions, setExtraSessions] = useState<ChatSessionDto[]>([])
  const [extraLoading, setExtraLoading] = useState(false)

  const refetchExtra = useCallback(async () => {
    if (useFallback) return
    setExtraLoading(true)
    try {
      const res = await chatApi.listSessions({
        project_id: projectFilter,
        include_project_chats: !projectFilter && includeProjectChats,
      })
      setExtraSessions(
        res.sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      )
    } catch {
      setExtraSessions([])
    } finally {
      setExtraLoading(false)
    }
  }, [useFallback, projectFilter, includeProjectChats])

  useEffect(() => {
    void refetchExtra()
  }, [refetchExtra])

  // Live updates: when a session is created / deleted / pinned /
  // project-assigned the project-scoped or include-projects list
  // needs a refresh. Subscribing here keeps the live behaviour close
  // to what ``useChatSessions`` provides for the default list.
  useEffect(() => {
    if (useFallback) return
    const refresh = (_event: BaseEvent) => {
      void refetchExtra()
    }
    const unsubs = [
      eventBus.on(Topics.CHAT_SESSION_CREATED, refresh),
      eventBus.on(Topics.CHAT_SESSION_DELETED, refresh),
      eventBus.on(Topics.CHAT_SESSION_PINNED_UPDATED, refresh),
      eventBus.on(Topics.CHAT_SESSION_PROJECT_UPDATED, refresh),
      eventBus.on(Topics.CHAT_SESSION_TITLE_UPDATED, refresh),
    ]
    return () => unsubs.forEach((u) => u())
  }, [useFallback, refetchExtra])

  const sessions = useFallback ? defaultSessions : extraSessions
  const isLoading = useFallback ? defaultLoading : extraLoading

  // Sanitised mode: hide chats whose project is NSFW. Project info
  // only flows into the list when project chats are visible (toggle
  // on or single-project mode); when off the list contains no
  // project-bound sessions at all.
  const nsfwProjectIds = useMemo(
    () =>
      new Set(
        Object.values(projects)
          .filter((p) => p.nsfw)
          .map((p) => p.id),
      ),
    [projects],
  )

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
        const excludeIds = isSanitised
          ? personas.filter((p) => p.nsfw).map((p) => p.id)
          : undefined
        const results = await chatApi.searchSessions({
          q: trimmed,
          persona_id: personaFilter !== 'all' ? personaFilter : undefined,
          exclude_persona_ids: excludeIds,
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
  }, [search, personaFilter, isSanitised, personas])

  // Filter sessions by sanitised mode, persona filter and (in
  // single-project mode) the project filter; use backend results when
  // searching. Note: when ``projectFilter`` is set the backend already
  // restricts to that project; the filter is reapplied client-side
  // here for consistency with the search-results path which calls a
  // different endpoint that doesn't know about ``projectFilter``.
  const filtered = useMemo(() => {
    let result = searchResults !== null ? searchResults : sessions

    if (projectFilter) {
      result = result.filter((s) => s.project_id === projectFilter)
    }

    if (isSanitised) {
      result = result.filter((s) => !nsfwPersonaIds.has(s.persona_id))
      // Hide chats whose project is NSFW too.
      result = result.filter(
        (s) => !s.project_id || !nsfwProjectIds.has(s.project_id),
      )
    }

    if (personaFilter !== 'all') {
      result = result.filter((s) => s.persona_id === personaFilter)
    }

    return result
  }, [
    sessions,
    searchResults,
    personaFilter,
    isSanitised,
    nsfwPersonaIds,
    nsfwProjectIds,
    projectFilter,
  ])

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
    const drawerOpen = useDrawerStore.getState().sidebarOpen
    navigate(
      `/chat/${session.persona_id}/${session.id}`,
      drawerOpen ? { replace: true } : undefined,
    )
    onClose()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0 flex flex-col sm:flex-row gap-2">
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
          className="w-full sm:w-auto bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
          style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 12 12%27%3E%3Cpath d=%27M3 5l3 3 3-3%27 fill=%27none%27 stroke=%27rgba(255,255,255,0.3)%27 stroke-width=%271.5%27/%3E%3C/svg%3E")', backgroundRepeat: 'no-repeat', backgroundPosition: 'right 6px center' }}
        >
          <option value="all" style={OPTION_STYLE}>All Personas</option>
          {filterPersonas.map((p) => (
            <option key={p.id} value={p.id} style={OPTION_STYLE}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* Mindspace: include-project-chats toggle. Lives on the global
          UserModal context only — the single-project context already
          implies "yes, project chats". */}
      {!projectFilter && (
        <div className="px-4 pb-2 flex-shrink-0">
          <label className="flex items-center gap-2 text-[11px] font-mono text-white/55 cursor-pointer">
            <input
              type="checkbox"
              checked={includeProjectChats}
              onChange={(e) => setIncludeProjectChats(e.target.checked)}
              data-testid="history-include-project-chats"
              className="h-3.5 w-3.5 cursor-pointer"
            />
            Include project chats
          </label>
        </div>
      )}

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
            <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-widest text-white/30 font-mono">
              {group}
            </div>
            {groupSessions.map((s) => {
              const persona = personas.find((p) => p.id === s.persona_id)
              // Show the project pill only when project chats are
              // mixed into the list (toggle on, no projectFilter); in
              // single-project mode every row would show the same
              // pill which would be visual noise.
              const showProjectPill =
                !projectFilter && includeProjectChats && !!s.project_id
              const project = showProjectPill && s.project_id
                ? projects[s.project_id] ?? null
                : null
              return (
                <SessionRow
                  key={s.id}
                  session={s}
                  personaName={persona?.name ?? s.persona_id}
                  monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                  colourScheme={persona?.colour_scheme}
                  projectPill={project ? { emoji: project.emoji, title: project.title } : null}
                  onOpen={() => handleOpen(s)}
                  isPinned={s.pinned}
                  onTogglePin={async () => {
                    try {
                      await chatApi.updateSessionPinned(s.id, !s.pinned)
                    } catch {
                      // pin event arrives via WS; non-critical
                    }
                  }}
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
  /**
   * Mindspace: when set, the row renders a small ``[emoji] title``
   * pill next to the session title so users can see at a glance
   * which project a session belongs to. Phase 9 / spec §6.5 Tab 3.
   */
  projectPill?: { emoji: string | null; title: string } | null
  onOpen: () => void
  isPinned: boolean
  onTogglePin: () => void
}

function SessionRow({ session, personaName, monogram, colourScheme, projectPill, onOpen, isPinned, onTogglePin }: SessionRowProps) {
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
    <div
      className="group rounded-lg transition-colors hover:bg-white/4"
      style={isPinned ? PINNED_STRIPE_STYLE : undefined}
    >
      <div className="flex items-start gap-3 px-3 py-2.5 [@media(hover:hover)]:items-center">
        {/* Persona monogram */}
        {chakra && monogram && (
          <div
            className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[8px] font-serif mt-0.5 [@media(hover:hover)]:mt-0"
            style={{
              background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}10 80%)`,
              color: `${chakra.hex}CC`,
            }}
          >
            {monogram}
          </div>
        )}

        {/* Inner container: stacks title+actions on touch, sits side-by-side on hover-capable devices */}
        <div className="flex-1 min-w-0 flex flex-col gap-1.5 [@media(hover:hover)]:flex-row [@media(hover:hover)]:items-center [@media(hover:hover)]:gap-3">
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

          {/* Actions — second row on touch, hover-faded inline on hover-capable */}
          <div className="flex items-center gap-1 flex-shrink-0 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 transition-opacity">
            <button
              type="button"
              onClick={onTogglePin}
              aria-label={isPinned ? 'Unpin session' : 'Pin session'}
              title={isPinned ? 'Unpin' : 'Pin'}
              className={`${BTN_NEUTRAL} ${isPinned ? 'text-gold border-gold/30' : ''}`}
            >
              📌
            </button>
            <button
              type="button"
              onClick={startEdit}
              aria-label="Rename session"
              title="Rename"
              className={BTN_NEUTRAL}
            >
              REN
            </button>
            <button
              type="button"
              onClick={handleGenerateTitle}
              disabled={generating}
              aria-label="Generate session title"
              title="Generate title"
              className={`${BTN_NEUTRAL} ${generating ? 'opacity-60 cursor-not-allowed' : ''} ${genSuccess ? 'text-gold' : ''}`}
            >
              {generating ? (
                <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-white/20 border-t-white/50" />
              ) : genSuccess ? 'OK' : 'GEN'}
            </button>
            {confirmDelete ? (
              <button ref={sureRef} type="button" onClick={handleDelete} aria-label="Confirm delete session" title="Confirm delete" className={BTN_RED}>
                SURE?
              </button>
            ) : (
              <button type="button" onClick={startDeleteConfirm} aria-label="Delete session" title="Delete session" className={BTN_NEUTRAL}>
                DEL
              </button>
            )}
            <span role="status" aria-live="polite" className="sr-only">
              {confirmDelete ? 'Confirm delete: press SURE to remove this session.' : ''}
            </span>
          </div>
        </div>

        {/* Open arrow */}
        <span
          className="text-[11px] text-white/20 group-hover:text-gold/50 transition-colors flex-shrink-0 cursor-pointer mt-0.5 [@media(hover:hover)]:mt-0"
          onClick={onOpen}
        >
          ›
        </span>
      </div>
    </div>
  )
}
