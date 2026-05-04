// Desktop project picker — small dropdown anchored to the
// ProjectSwitcher chevron in the chat top-bar. Spec §6.2 fixes both
// the row order and the always-present search input:
//
//   1. "— No project" row
//   2. Search input
//   3. Filtered project list (sanitised-mode aware)
//   4. Divider
//   5. "+ Create new project…" row
//
// The picker is purely presentational; the heavy lifting (assigning
// the session, opening the create-modal, closing on success) happens
// here via ``projectsApi.setSessionProject`` and the
// ``ProjectCreateModal``.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNotificationStore } from '../../core/store/notificationStore'
import { projectsApi } from './projectsApi'
import { useFilteredProjects } from './useProjectsStore'
import { ProjectCreateModal } from './ProjectCreateModal'
import type { ProjectDto } from './types'

interface ProjectPickerProps {
  sessionId: string
  currentProjectId: string | null
  onClose: () => void
}

export function ProjectPicker({
  sessionId,
  currentProjectId,
  onClose,
}: ProjectPickerProps) {
  const filteredProjects = useFilteredProjects()
  const addNotification = useNotificationStore((s) => s.addNotification)

  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const containerRef = useRef<HTMLDivElement>(null)

  // Outside click closes the picker (but only when the create-modal
  // isn't covering it — its own backdrop owns that interaction).
  useEffect(() => {
    if (createOpen) return
    function handler(e: MouseEvent) {
      const node = containerRef.current
      if (!node) return
      if (!node.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [createOpen, onClose])

  // Esc closes (the modal-aware version mirrors the outside-click
  // guard so the user's Esc tap on the modal is consumed by the
  // modal first).
  useEffect(() => {
    if (createOpen) return
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [createOpen, onClose])

  // Search filter on top of the shared ``useFilteredProjects`` selector
  // (NSFW filter applied centrally — see useProjectsStore.ts).
  const visibleProjects = useMemo(() => {
    const term = query.trim().toLowerCase()
    return filteredProjects.filter((p) =>
      term ? p.title.toLowerCase().includes(term) : true,
    )
  }, [filteredProjects, query])

  async function assign(projectId: string | null) {
    if (busy) return
    setBusy(true)
    try {
      await projectsApi.setSessionProject(sessionId, projectId)
      // The backend emits CHAT_SESSION_PROJECT_UPDATED;
      // useChatSessions picks that up and re-renders the switcher.
      onClose()
    } catch {
      addNotification({
        level: 'error',
        title: 'Switch failed',
        message: 'Could not assign the chat to that project.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function handleCreated(project: ProjectDto) {
    setCreateOpen(false)
    // Auto-assign the new project to the active session, mirroring
    // the spec: "+ Create new project… → on success auto-assigns".
    await assign(project.id)
  }

  return (
    <>
      <div
        ref={containerRef}
        role="listbox"
        aria-label="Switch project"
        className="absolute right-0 top-full z-50 mt-1.5 w-72 overflow-hidden rounded-md border border-white/8 bg-[#0f0d16] shadow-xl"
      >
        {/* "— No project" row */}
        <button
          type="button"
          role="option"
          aria-selected={currentProjectId === null}
          disabled={busy}
          onClick={() => assign(null)}
          className={[
            'flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] transition-colors',
            currentProjectId === null
              ? 'bg-white/5 text-white/85'
              : 'text-white/65 hover:bg-white/5 hover:text-white/85',
          ].join(' ')}
        >
          <span aria-hidden="true" className="text-[14px] leading-none">—</span>
          <span className="flex-1 truncate">No project</span>
        </button>

        {/* Always-present search input */}
        <div className="border-y border-white/5 px-2 py-1.5">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects…"
            // Auto-focus the search input so keyboard users can start
            // typing immediately without an extra Tab.
            autoFocus
            className="w-full rounded-md border border-white/6 bg-white/4 px-2 py-1 text-[12px] text-white/80 placeholder-white/35 outline-none transition-colors focus:border-white/12 focus:bg-white/6"
          />
        </div>

        {/* Project list */}
        <div className="max-h-64 overflow-y-auto py-1">
          {visibleProjects.length === 0 ? (
            <p className="px-3 py-3 text-center text-[12px] text-white/45">
              {query.trim() ? 'No matching projects' : 'No projects yet'}
            </p>
          ) : (
            visibleProjects.map((p) => (
              <button
                key={p.id}
                type="button"
                role="option"
                aria-selected={currentProjectId === p.id}
                disabled={busy}
                onClick={() => assign(p.id)}
                className={[
                  'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] transition-colors',
                  currentProjectId === p.id
                    ? 'bg-white/5 text-white/85'
                    : 'text-white/70 hover:bg-white/5 hover:text-white/90',
                ].join(' ')}
              >
                <span aria-hidden="true" className="text-[14px] leading-none">
                  {p.emoji ?? '·'}
                </span>
                <span className="flex-1 truncate">{p.title}</span>
                {p.pinned && (
                  <span aria-hidden="true" className="text-[11px] text-gold/70">
                    ★
                  </span>
                )}
              </button>
            ))
          )}
        </div>

        {/* Divider + create row */}
        <div className="border-t border-white/5">
          <button
            type="button"
            disabled={busy}
            onClick={() => setCreateOpen(true)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-white/65 transition-colors hover:bg-white/5 hover:text-white/85"
          >
            <span aria-hidden="true">+</span>
            <span className="flex-1">Create new project…</span>
          </button>
        </div>
      </div>

      {createOpen && (
        <ProjectCreateModal
          isOpen={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={handleCreated}
        />
      )}
    </>
  )
}
