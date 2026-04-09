import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  DndContext,
  DragOverlay,
  closestCenter,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { zoomModifiers } from "../../../core/utils/dndZoomModifier"
import { bookmarksApi } from '../../../core/api/bookmarks'
import { useBookmarks } from '../../../core/hooks/useBookmarks'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useDndSensors } from '../../../core/hooks/useDndSensors'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE, type ChakraColour } from '../../../core/types/chakra'
import type { BookmarkDto } from '../../../core/types/bookmark'

interface BookmarksTabProps {
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

function groupBookmarks(bookmarks: BookmarkDto[]): [string, BookmarkDto[]][] {
  const map = new Map<string, BookmarkDto[]>()
  for (const b of bookmarks) {
    const group = getDateGroup(b.created_at)
    const existing = map.get(group) ?? []
    map.set(group, [...existing, b])
  }
  return Array.from(map.entries())
}

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

export function BookmarksTab({ onClose }: BookmarksTabProps) {
  const { bookmarks, setBookmarks, isLoading } = useBookmarks()
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

  // Filter: global only, sanitised mode, persona filter, text search
  const filtered = useMemo(() => {
    let result = bookmarks.filter((b) => b.scope === 'global')

    if (isSanitised) {
      result = result.filter((b) => !nsfwPersonaIds.has(b.persona_id))
    }

    if (personaFilter !== 'all') {
      result = result.filter((b) => b.persona_id === personaFilter)
    }

    if (search.trim()) {
      const term = search.toLowerCase()
      result = result.filter((b) => {
        const personaName = personas.find((p) => p.id === b.persona_id)?.name ?? ''
        return (
          b.title.toLowerCase().includes(term) ||
          personaName.toLowerCase().includes(term)
        )
      })
    }

    return result
  }, [bookmarks, search, personas, personaFilter, isSanitised, nsfwPersonaIds])

  // Personas available for the filter dropdown (only those with global bookmarks, respecting sanitised mode)
  const filterPersonas = useMemo(() => {
    const globalBookmarks = bookmarks.filter((b) => b.scope === 'global')
    const personaIdsWithBookmarks = new Set(globalBookmarks.map((b) => b.persona_id))
    return personas
      .filter((p) => personaIdsWithBookmarks.has(p.id))
      .filter((p) => !isSanitised || !p.nsfw)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [personas, bookmarks, isSanitised])

  const grouped = useMemo(() => groupBookmarks(filtered), [filtered])

  const [dragActiveId, setDragActiveId] = useState<string | null>(null)
  const dragActive = dragActiveId ? filtered.find((b) => b.id === dragActiveId) : null

  const dndSensors = useDndSensors()
  function handleDragStart(event: DragStartEvent) { setDragActiveId(event.active.id as string) }
  function handleDragEnd(event: DragEndEvent) {
    setDragActiveId(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIdx = filtered.findIndex((b) => b.id === active.id)
    const newIdx = filtered.findIndex((b) => b.id === over.id)
    if (oldIdx === -1 || newIdx === -1) return
    const reordered = arrayMove(filtered, oldIdx, newIdx)
    // Apply new order to the full bookmarks list
    const orderMap = new Map(reordered.map((b, i) => [b.id, i]))
    setBookmarks((prev) => [...prev].sort((a, b) => (orderMap.get(a.id) ?? a.display_order) - (orderMap.get(b.id) ?? b.display_order)))
    bookmarksApi.reorder(reordered.map((b) => b.id)).catch(() => {})
  }

  function handleOpen(bookmark: BookmarkDto) {
    navigate(`/chat/${bookmark.persona_id}/${bookmark.session_id}?msg=${bookmark.message_id}`)
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
          placeholder="Search bookmarks..."
          aria-label="Search bookmarks"
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
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">Loading...</p>
        )}
        {!isLoading && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-16 px-4">
            <p className="text-[12px] font-mono text-white/60">No bookmarks yet</p>
            <p className="max-w-xs text-center text-[11px] text-white/60 leading-relaxed">
              Bookmark a chat message from any conversation to find it again here.
            </p>
          </div>
        )}
        <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <SortableContext items={filtered.map((b) => b.id)} strategy={verticalListSortingStrategy}>
            {grouped.map(([group, groupBookmarks]) => (
              <div key={group}>
                <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-widest text-white/30 font-mono">
                  {group}
                </div>
                {groupBookmarks.map((b) => {
                  const persona = personas.find((p) => p.id === b.persona_id)
                  return (
                    <SortableBookmarkRow
                      key={b.id}
                      bookmark={b}
                      personaName={persona?.name ?? b.persona_id}
                      monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                      colourScheme={persona?.colour_scheme}
                      onOpen={() => handleOpen(b)}
                      onUpdated={(updated) => setBookmarks((prev) => prev.map((bm) => bm.id === updated.id ? updated : bm))}
                    />
                  )
                })}
              </div>
            ))}
          </SortableContext>
          <DragOverlay modifiers={zoomModifiers}>
            {dragActive ? (
              <div className="rounded-lg border border-white/10 bg-elevated px-3 py-1.5 text-[13px] text-white/70 shadow-xl">
                {dragActive.title}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>
    </div>
  )
}


function SortableBookmarkRow(props: BookmarkRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: props.bookmark.id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }
  return (
    <div ref={setNodeRef} style={style}>
      <BookmarkRow {...props} dragListeners={listeners} dragAttributes={attributes} onUpdated={props.onUpdated} />
    </div>
  )
}

interface BookmarkRowProps {
  bookmark: BookmarkDto
  personaName: string
  monogram?: string
  colourScheme?: ChakraColour
  onOpen: () => void
  dragListeners?: DraggableSyntheticListeners
  dragAttributes?: DraggableAttributes
  onUpdated?: (updated: BookmarkDto) => void
}

function BookmarkRow({ bookmark, personaName, monogram, colourScheme, onOpen, dragListeners, dragAttributes, onUpdated }: BookmarkRowProps) {
  const chakra = colourScheme ? CHAKRA_PALETTE[colourScheme] : null
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
    setEditValue(bookmark.title)
    setEditing(true)
  }, [bookmark.title])

  const cancelEdit = useCallback(() => {
    setEditing(false)
    setEditValue('')
  }, [])

  const saveEdit = useCallback(async () => {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === bookmark.title) {
      cancelEdit()
      return
    }
    try {
      const updated = await bookmarksApi.update(bookmark.id, { title: trimmed })
      onUpdated?.(updated)
    } catch {
      // Event fallback
    }
    setEditing(false)
  }, [editValue, bookmark.id, bookmark.title, cancelEdit, onUpdated])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveEdit()
    if (e.key === 'Escape') cancelEdit()
  }, [saveEdit, cancelEdit])

  const handleDelete = useCallback(async () => {
    try {
      await bookmarksApi.remove(bookmark.id)
    } catch {
      // Removal via event
    }
    setConfirmDelete(false)
  }, [bookmark.id])

  const startDeleteConfirm = useCallback(() => {
    setConfirmDelete(true)
  }, [])

  return (
    <div className="group rounded-lg transition-colors hover:bg-white/4">
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Drag handle */}
        {dragListeners && (
          <span
            className="w-0 overflow-hidden cursor-grab select-none text-[10px] leading-none text-white/15 group-hover:w-auto group-hover:text-white/30 transition-all flex-shrink-0"
            {...(dragListeners ?? {})}
            {...(dragAttributes ?? {})}
          >
            ⠿
          </span>
        )}
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

        {/* Main content */}
        {editing ? (
          <div className="flex-1 min-w-0">
            <input
              ref={inputRef}
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={saveEdit}
              className="w-full bg-white/[0.04] border border-gold/30 rounded px-2 py-0.5 text-[13px] text-white/80 outline-none font-mono"
            />
            <div className="flex items-center gap-2 mt-0.5">
              <p className="text-[10px] text-white/40 font-mono truncate">{personaName}</p>
            </div>
          </div>
        ) : (
          <button type="button" onClick={onOpen} className="flex-1 min-w-0 text-left">
            <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
              {bookmark.title}
            </p>
            <div className="flex items-center gap-2 mt-0.5">
              <p className="text-[10px] text-white/40 font-mono truncate">{personaName}</p>
            </div>
          </button>
        )}

        {/* Actions — visible on hover */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            type="button"
            onClick={startEdit}
            aria-label={`Edit bookmark title ${bookmark.title}`}
            title="Edit title"
            className={BTN_NEUTRAL}
          >
            EDIT
          </button>
          {confirmDelete ? (
            <button ref={sureRef} type="button" onClick={handleDelete} aria-label="Confirm delete bookmark" title="Confirm delete" className={BTN_RED}>
              SURE?
            </button>
          ) : (
            <button type="button" onClick={startDeleteConfirm} aria-label={`Delete bookmark ${bookmark.title}`} title="Delete bookmark" className={BTN_NEUTRAL}>
              DEL
            </button>
          )}
          <span role="status" aria-live="polite" className="sr-only">
            {confirmDelete ? 'Confirm delete: press SURE to remove this bookmark.' : ''}
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
