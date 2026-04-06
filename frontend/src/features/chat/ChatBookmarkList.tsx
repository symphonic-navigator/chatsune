import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import {
  DndContext,
  DragOverlay,
  closestCenter,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { zoomModifiers } from "../../core/utils/dndZoomModifier"
import type { BookmarkDto } from '../../core/types/bookmark'
import { bookmarksApi } from '../../core/api/bookmarks'

interface ChatBookmarkListProps {
  bookmarks: BookmarkDto[]
  onScrollTo: (messageId: string) => void
  onClose: () => void
  onBookmarksReordered: (reordered: BookmarkDto[]) => void
  onBookmarkUpdated: (updated: BookmarkDto) => void
}

export function ChatBookmarkList({ bookmarks, onScrollTo, onClose, onBookmarksReordered, onBookmarkUpdated }: ChatBookmarkListProps) {
  const [dragActiveId, setDragActiveId] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  // Close on outside click — but not when clicking portal menus
  useEffect(() => {
    function handler(e: MouseEvent) {
      const target = e.target as HTMLElement
      if (panelRef.current && !panelRef.current.contains(target) && !target.closest('[data-bookmark-portal]')) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  function handleDragStart(event: DragStartEvent) {
    setDragActiveId(event.active.id as string)
  }

  function handleDragEnd(event: DragEndEvent) {
    setDragActiveId(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = bookmarks.findIndex((b) => b.id === active.id)
    const newIndex = bookmarks.findIndex((b) => b.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reordered = arrayMove(bookmarks, oldIndex, newIndex)
    onBookmarksReordered(reordered)
    bookmarksApi.reorder(reordered.map((b) => b.id)).catch(() => {})
  }

  const dragActive = dragActiveId ? bookmarks.find((b) => b.id === dragActiveId) : null

  return (
    <div
      ref={panelRef}
      className="absolute right-0 top-full mt-1 z-50 w-72 rounded-lg border border-white/10 bg-elevated shadow-xl"
    >
      <DndContext collisionDetection={closestCenter} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <SortableContext items={bookmarks.map((b) => b.id)} strategy={verticalListSortingStrategy}>
          <div className="py-1 max-h-[300px] overflow-y-auto">
            {bookmarks.map((bm) => (
              <SortableBookmarkItem
                key={bm.id}
                bookmark={bm}
                onScrollTo={onScrollTo}
                onClose={onClose}
                onUpdated={onBookmarkUpdated}
              />
            ))}
          </div>
        </SortableContext>
        <DragOverlay modifiers={zoomModifiers}>
          {dragActive ? (
            <div className="rounded border border-white/10 bg-elevated px-3 py-1.5 text-[12px] text-white/60 shadow-xl">
              {dragActive.title}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}


function SortableBookmarkItem({ bookmark, onScrollTo, onClose, onUpdated }: {
  bookmark: BookmarkDto
  onScrollTo: (messageId: string) => void
  onClose: () => void
  onUpdated: (updated: BookmarkDto) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: bookmark.id })
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPos, setMenuPos] = useState({ x: 0, y: 0 })
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(bookmark.title)
  const [editScope, setEditScope] = useState(bookmark.scope)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  useEffect(() => {
    if (!menuOpen) return
    function handler(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
        setConfirmDelete(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [menuOpen])

  async function saveEdit() {
    const updates: Record<string, unknown> = {}
    if (editTitle.trim() && editTitle.trim() !== bookmark.title) updates.title = editTitle.trim()
    if (editScope !== bookmark.scope) updates.scope = editScope
    if (Object.keys(updates).length > 0) {
      try {
        const updated = await bookmarksApi.update(bookmark.id, updates as { title?: string; scope?: 'global' | 'local' })
        onUpdated(updated)
      } catch { /* event fallback */ }
    }
    setEditing(false)
  }

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  }

  if (editing) {
    return (
      <div ref={setNodeRef} style={style} className="px-3 py-2 border-b border-white/5">
        <input
          ref={inputRef}
          type="text"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') setEditing(false) }}
          className="w-full bg-white/[0.04] border border-white/10 rounded px-2 py-1 text-[12px] text-white/80 outline-none font-mono mb-1.5"
        />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setEditScope('local')}
            className={`px-2 py-0.5 rounded text-[10px] font-mono ${editScope === 'local' ? 'bg-white/10 text-white/70' : 'text-white/30'}`}
          >
            Local
          </button>
          <button
            type="button"
            onClick={() => setEditScope('global')}
            className={`px-2 py-0.5 rounded text-[10px] font-mono ${editScope === 'global' ? 'bg-gold/20 text-gold' : 'text-white/30'}`}
          >
            Global
          </button>
          <div className="flex-1" />
          <button onClick={() => setEditing(false)} className="text-[10px] text-white/30 font-mono">Cancel</button>
          <button onClick={saveEdit} className="text-[10px] text-white/60 font-mono">Save</button>
        </div>
      </div>
    )
  }

  return (
    <div ref={setNodeRef} style={style} className="group relative flex items-center gap-1.5 px-2 py-1.5 transition-colors hover:bg-white/6">
      {/* Drag handle */}
      <span
        className="w-0 overflow-hidden cursor-grab select-none text-[10px] leading-none text-white/15 group-hover:w-auto group-hover:text-white/30 transition-all flex-shrink-0"
        {...listeners}
        {...attributes}
      >
        ⠿
      </span>

      {/* Bookmark icon */}
      <svg width="10" height="10" viewBox="0 0 14 14" className={`flex-shrink-0 ${bookmark.scope === 'global' ? 'text-gold' : 'text-white/30'}`} fill="currentColor">
        <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1" strokeLinejoin="round" />
      </svg>

      {/* Title — clickable to scroll */}
      <button
        type="button"
        onClick={() => { onScrollTo(bookmark.message_id); onClose() }}
        className="flex-1 text-left text-[12px] text-white/60 truncate hover:text-white/80 transition-colors"
      >
        {bookmark.title}
      </button>

      {/* Menu trigger */}
      <button
        ref={triggerRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          const rect = triggerRef.current?.getBoundingClientRect()
          if (rect) setMenuPos({ x: rect.right, y: rect.bottom + 4 })
          setMenuOpen(true)
        }}
        className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded text-[10px] text-white/25 opacity-0 group-hover:opacity-100 transition-all hover:text-white/50"
      >
        ···
      </button>

      {/* Context menu — rendered via portal to escape overflow clipping */}
      {menuOpen && createPortal(
        <div
          ref={menuRef}
          data-bookmark-portal
          className="fixed z-[100] w-32 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
          style={{ left: menuPos.x - 128, top: menuPos.y }}
        >
          <button
            type="button"
            onClick={() => { setMenuOpen(false); setEditing(true); setEditTitle(bookmark.title); setEditScope(bookmark.scope) }}
            className="w-full px-3 py-1.5 text-left text-[12px] text-white/60 transition-colors hover:bg-white/6"
          >
            Edit
          </button>
          {confirmDelete ? (
            <button
              type="button"
              onClick={async () => {
                await bookmarksApi.remove(bookmark.id).catch(() => {})
                setMenuOpen(false)
              }}
              className="w-full px-3 py-1.5 text-left text-[12px] text-red-400 transition-colors hover:bg-red-400/10"
            >
              Confirm?
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="w-full px-3 py-1.5 text-left text-[12px] text-white/60 transition-colors hover:bg-white/6"
            >
              Delete
            </button>
          )}
        </div>,
        document.body,
      )}
    </div>
  )
}
