import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { artefactApi } from '../../../core/api/artefact'
import { eventBus } from '../../../core/websocket/eventBus'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { Topics } from '../../../core/types/events'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import type { ChakraColour } from '../../../core/types/chakra'
import type { ArtefactListItem, ArtefactType } from '../../../core/types/artefact'
import type { BaseEvent } from '../../../core/types/events'
import { applyArtefactFilters } from './artefactsFilter'

interface ArtefactsTabProps {
  onClose: () => void
}

const ARTEFACT_TYPES: ArtefactType[] = ['markdown', 'code', 'html', 'svg', 'jsx', 'mermaid']

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

export function ArtefactsTab({ onClose }: ArtefactsTabProps) {
  const [items, setItems] = useState<ArtefactListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [personaFilter, setPersonaFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<ArtefactType | 'all'>('all')
  const { personas } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const navigate = useNavigate()

  const fetchAll = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await artefactApi.listAll()
      setItems(data)
    } catch {
      setError('Could not load artefacts.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  // Subscribe to artefact lifecycle events
  useEffect(() => {
    const handleEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>

      switch (event.type) {
        case Topics.ARTEFACT_CREATED: {
          // Can't enrich a new item without a round-trip — refetch the full list
          fetchAll()
          break
        }
        case Topics.ARTEFACT_UPDATED: {
          setItems((prev) =>
            prev.map((a) =>
              a.session_id === (p.session_id as string) && a.handle === (p.handle as string)
                ? {
                    ...a,
                    title: (p.title as string) ?? a.title,
                    size_bytes: (p.size_bytes as number) ?? a.size_bytes,
                    version: (p.version as number) ?? a.version,
                    updated_at: event.timestamp,
                  }
                : a,
            ),
          )
          break
        }
        case Topics.ARTEFACT_DELETED: {
          setItems((prev) =>
            prev.filter(
              (a) => !(a.session_id === (p.session_id as string) && a.handle === (p.handle as string)),
            ),
          )
          break
        }
      }
    }

    const unsubs = [
      eventBus.on(Topics.ARTEFACT_CREATED, handleEvent),
      eventBus.on(Topics.ARTEFACT_UPDATED, handleEvent),
      eventBus.on(Topics.ARTEFACT_DELETED, handleEvent),
    ]
    return () => unsubs.forEach((u) => u())
  }, [fetchAll])

  const nsfwPersonaIds = useMemo(
    () => new Set(personas.filter((p) => p.nsfw).map((p) => p.id)),
    [personas],
  )

  const filtered = useMemo(
    () =>
      applyArtefactFilters(items, {
        isSanitised,
        nsfwPersonaIds,
        personaFilter,
        typeFilter,
        search,
      }),
    [items, isSanitised, nsfwPersonaIds, personaFilter, typeFilter, search],
  )

  // Personas that have at least one visible artefact, sorted by name
  const filterPersonas = useMemo(() => {
    const visiblePersonaIds = new Set(filtered.map((a) => a.persona_id))
    // Also include ids from all items so filter options don't disappear mid-filter
    const allPersonaIds = new Set(items.map((a) => a.persona_id))
    return personas
      .filter((p) => allPersonaIds.has(p.id))
      .filter((p) => !isSanitised || !p.nsfw)
      // Prioritise personas with visible results but show all that have artefacts
      .filter((p) => visiblePersonaIds.has(p.id) || personaFilter === p.id)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [personas, items, filtered, isSanitised, personaFilter])

  function handleOpen(row: ArtefactListItem) {
    navigate(`/chat/${row.persona_id}/${row.session_id}`, {
      state: { pendingArtefactId: row.id },
    })
    onClose()
  }

  const handleRename = useCallback(
    async (row: ArtefactListItem, title: string) => {
      // Optimistic update
      setItems((prev) =>
        prev.map((a) =>
          a.id === row.id ? { ...a, title } : a,
        ),
      )
      try {
        await artefactApi.patch(row.session_id, row.id, { title })
      } catch {
        // Revert on failure
        setItems((prev) =>
          prev.map((a) =>
            a.id === row.id ? { ...a, title: row.title } : a,
          ),
        )
      }
    },
    [],
  )

  const handleDelete = useCallback(
    async (row: ArtefactListItem) => {
      // Optimistic removal
      setItems((prev) => prev.filter((a) => a.id !== row.id))
      try {
        await artefactApi.delete(row.session_id, row.id)
      } catch {
        // Refetch to restore state
        fetchAll()
      }
    },
    [fetchAll],
  )

  const SELECT_CLASSES =
    'bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6'
  const SELECT_STYLE = {
    backgroundImage:
      'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 12 12%27%3E%3Cpath d=%27M3 5l3 3 3-3%27 fill=%27none%27 stroke=%27rgba(255,255,255,0.3)%27 stroke-width=%271.5%27/%3E%3C/svg%3E")',
    backgroundRepeat: 'no-repeat' as const,
    backgroundPosition: 'right 6px center' as const,
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search artefacts..."
          aria-label="Search artefacts"
          className="flex-1 bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none focus:border-gold/30 transition-colors font-mono"
        />
        <select
          value={personaFilter}
          onChange={(e) => setPersonaFilter(e.target.value)}
          aria-label="Filter by persona"
          className={SELECT_CLASSES}
          style={SELECT_STYLE}
        >
          <option value="all">All Personas</option>
          {filterPersonas.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as ArtefactType | 'all')}
          aria-label="Filter by type"
          className={SELECT_CLASSES}
          style={SELECT_STYLE}
        >
          <option value="all">All Types</option>
          {ARTEFACT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {isLoading && (
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">Loading...</p>
        )}
        {!isLoading && error && (
          <p className="px-4 py-3 text-[12px] text-red-400 font-mono">{error}</p>
        )}
        {!isLoading && !error && filtered.length === 0 && (
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">No artefacts found.</p>
        )}
        {!isLoading && !error && filtered.map((item) => (
          <ArtefactRow
            key={item.id}
            item={item}
            onOpen={() => handleOpen(item)}
            onRename={(title) => handleRename(item, title)}
            onDelete={() => handleDelete(item)}
          />
        ))}
      </div>
    </div>
  )
}


interface ArtefactRowProps {
  item: ArtefactListItem
  onOpen: () => void
  onRename: (title: string) => void
  onDelete: () => void
}

function ArtefactRow({ item, onOpen, onRename, onDelete }: ArtefactRowProps) {
  const chakra = CHAKRA_PALETTE[item.persona_colour_scheme as ChakraColour] ?? null
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
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

  const startEdit = useCallback(() => {
    setEditValue(item.title)
    setEditing(true)
  }, [item.title])

  const cancelEdit = useCallback(() => {
    setEditing(false)
    setEditValue('')
  }, [])

  const saveEdit = useCallback(async () => {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === item.title) {
      cancelEdit()
      return
    }
    onRename(trimmed)
    setEditing(false)
  }, [editValue, item.title, onRename, cancelEdit])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') saveEdit()
      if (e.key === 'Escape') cancelEdit()
    },
    [saveEdit, cancelEdit],
  )

  const handleDeleteConfirmed = useCallback(() => {
    onDelete()
    setConfirmDelete(false)
  }, [onDelete])

  return (
    <div className="group rounded-lg transition-colors hover:bg-white/4">
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Persona monogram */}
        {chakra && (
          <div
            className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[8px] font-serif"
            style={{
              background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}10 80%)`,
              color: `${chakra.hex}CC`,
            }}
          >
            {item.persona_monogram}
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
              <p
                className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors"
                onDoubleClick={(e) => { e.stopPropagation(); startEdit() }}
              >
                {item.title}
              </p>
            )}
            {!editing && (
              <span className="flex-shrink-0 text-[9px] font-mono uppercase tracking-wider px-1 py-0.5 rounded border border-white/10 text-white/30">
                {item.type}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[10px] text-white/40 font-mono truncate">
              {item.persona_name}
            </p>
            <span className="text-[10px] text-white/20">·</span>
            <p className="text-[10px] text-white/40 font-mono truncate">
              {item.session_title ?? 'untitled chat'}
            </p>
            <span className="text-[10px] text-white/20">·</span>
            <p className="text-[10px] text-white/30 font-mono flex-shrink-0">
              {formatDate(item.updated_at)}
            </p>
          </div>
        </button>

        {/* Actions — visible on hover */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            type="button"
            onClick={startEdit}
            aria-label="Rename artefact"
            title="Rename"
            className={BTN_NEUTRAL}
          >
            REN
          </button>
          {confirmDelete ? (
            <button
              ref={sureRef}
              type="button"
              onClick={handleDeleteConfirmed}
              aria-label="Confirm delete artefact"
              title="Confirm delete"
              className={BTN_RED}
            >
              SURE?
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              aria-label="Delete artefact"
              title="Delete artefact"
              className={BTN_NEUTRAL}
            >
              DEL
            </button>
          )}
          <button
            type="button"
            onClick={onOpen}
            aria-label="Open artefact in chat"
            title="Open in chat"
            className={BTN_NEUTRAL}
          >
            OPEN
          </button>
          <span role="status" aria-live="polite" className="sr-only">
            {confirmDelete ? 'Confirm delete: press SURE to remove this artefact.' : ''}
          </span>
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
