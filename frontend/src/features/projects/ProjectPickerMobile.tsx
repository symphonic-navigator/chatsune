// Mobile project picker — fullscreen overlay analogous to the
// "Start new chat" mobile flow (`MobileNewChatView` +
// `MobileSidebarHeader`). Same content as the desktop ProjectPicker
// but laid out single-column, with larger tap targets and a
// dedicated header carrying the back/close button.
//
// Lives in the same file family as `ProjectPicker.tsx`; the
// `ProjectSwitcher` chooses between the two via `useViewport`.

import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useSanitisedMode } from '../../core/store/sanitisedModeStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { lockBodyScroll, unlockBodyScroll } from '../../core/utils/bodyScrollLock'
import { projectsApi } from './projectsApi'
import { useSortedProjects } from './useProjectsStore'
import { ProjectCreateModal } from './ProjectCreateModal'
import type { ProjectDto } from './types'

interface ProjectPickerMobileProps {
  sessionId: string
  currentProjectId: string | null
  onClose: () => void
}

export function ProjectPickerMobile({
  sessionId,
  currentProjectId,
  onClose,
}: ProjectPickerMobileProps) {
  const sortedProjects = useSortedProjects()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const addNotification = useNotificationStore((s) => s.addNotification)

  const [query, setQuery] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  // Lock background scrolling for the lifetime of the overlay so the
  // chat behind doesn't scroll under the user's fingers.
  useEffect(() => {
    lockBodyScroll()
    return () => unlockBodyScroll()
  }, [])

  // Esc closes (mostly relevant for the dev-tools mobile emulator;
  // the back-arrow is the primary close affordance on touch).
  useEffect(() => {
    if (createOpen) return
    function handler(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [createOpen, onClose])

  const visibleProjects = useMemo(() => {
    const term = query.trim().toLowerCase()
    return sortedProjects
      .filter((p) => (isSanitised ? !p.nsfw : true))
      .filter((p) => (term ? p.title.toLowerCase().includes(term) : true))
  }, [sortedProjects, isSanitised, query])

  async function assign(projectId: string | null) {
    if (busy) return
    setBusy(true)
    try {
      await projectsApi.setSessionProject(sessionId, projectId)
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
    await assign(project.id)
  }

  // Render via portal so the overlay covers the chat top-bar too,
  // matching the "Start new chat" pattern.
  return createPortal(
    <>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Switch project"
        data-testid="project-picker-mobile"
        className="fixed inset-0 z-50 flex flex-col bg-base"
        style={{ paddingTop: 'env(safe-area-inset-top)' }}
      >
        {/* Header */}
        <div className="flex h-[50px] flex-shrink-0 items-center gap-2 border-b border-white/6 px-3">
          <button
            type="button"
            onClick={onClose}
            aria-label="Close project picker"
            className="flex h-9 w-9 items-center justify-center rounded-md text-white/65 transition-colors hover:bg-white/8 hover:text-white/90"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          <span className="text-[14px] font-semibold text-white/80">Switch project</span>
        </div>

        {/* Search */}
        <div className="flex-shrink-0 border-b border-white/5 px-3 py-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects…"
            className="w-full rounded-md border border-white/6 bg-white/4 px-3 py-2 text-[14px] text-white/85 placeholder-white/40 outline-none transition-colors focus:border-white/12 focus:bg-white/6"
          />
        </div>

        {/* Scrollable list */}
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {/* "— No project" */}
          <button
            type="button"
            role="option"
            aria-selected={currentProjectId === null}
            disabled={busy}
            onClick={() => assign(null)}
            className={[
              'flex w-full items-center gap-3 px-4 py-3 text-left text-[14px] transition-colors',
              currentProjectId === null
                ? 'bg-white/6 text-white/90'
                : 'text-white/70 hover:bg-white/4 hover:text-white/90',
            ].join(' ')}
          >
            <span aria-hidden="true" className="text-[18px] leading-none">—</span>
            <span className="flex-1 truncate">No project</span>
          </button>

          <div className="mx-4 my-1 h-px bg-white/4" />

          {visibleProjects.length === 0 ? (
            <p className="px-4 py-6 text-center text-[13px] text-white/45">
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
                  'flex w-full items-center gap-3 px-4 py-3 text-left text-[14px] transition-colors',
                  currentProjectId === p.id
                    ? 'bg-white/6 text-white/90'
                    : 'text-white/75 hover:bg-white/4 hover:text-white/90',
                ].join(' ')}
              >
                <span aria-hidden="true" className="text-[18px] leading-none">
                  {p.emoji ?? '·'}
                </span>
                <span className="flex-1 truncate">{p.title}</span>
                {p.pinned && (
                  <span aria-hidden="true" className="text-[12px] text-gold/70">
                    ★
                  </span>
                )}
              </button>
            ))
          )}
        </div>

        {/* Create row pinned to bottom */}
        <div className="flex-shrink-0 border-t border-white/6">
          <button
            type="button"
            disabled={busy}
            onClick={() => setCreateOpen(true)}
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-[14px] text-white/75 transition-colors hover:bg-white/4 hover:text-white/90"
          >
            <span aria-hidden="true" className="text-[16px]">+</span>
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
    </>,
    document.body,
  )
}
