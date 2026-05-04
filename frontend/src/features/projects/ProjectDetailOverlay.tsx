// Project-Detail-Overlay (Mindspace spec §6.5).
//
// Six-tab modal that reuses the same shell pattern as the persona
// overlay (`app/components/persona-overlay/PersonaOverlay.tsx`):
//   - absolute inset-0 lg:inset-4 z-20 panel
//   - opaque backdrop above z-10 that closes on click
//   - focus trap + Escape close
//   - return-focus-on-unmount via ``useBackButtonClose``
//
// Tabs: Overview · Personas · Chats · Uploads · Artefacts · Images.
// The four "shared" user-modal tabs (HistoryTab, UploadsTab,
// ArtefactsTab, ImagesTab) accept a ``projectFilter`` prop in
// Phase 9 and scope themselves automatically.

import { useEffect, useRef, useState } from 'react'
import { useBackButtonClose } from '../../core/hooks/useBackButtonClose'
import { useProjectsStore } from './useProjectsStore'
import { ProjectOverviewTab } from './tabs/ProjectOverviewTab'
import { ProjectPersonasTab } from './tabs/ProjectPersonasTab'
import { HistoryTab } from '../../app/components/user-modal/HistoryTab'
import { UploadsTab } from '../../app/components/user-modal/UploadsTab'
import { ArtefactsTab } from '../../app/components/user-modal/ArtefactsTab'
import { ImagesTab } from '../../app/components/user-modal/ImagesTab'

export type ProjectDetailTab =
  | 'overview'
  | 'personas'
  | 'chats'
  | 'uploads'
  | 'artefacts'
  | 'images'

interface ProjectDetailOverlayProps {
  projectId: string
  onClose: () => void
  initialTab?: ProjectDetailTab
}

interface TabDef {
  id: ProjectDetailTab
  label: string
}

const TABS: TabDef[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'personas', label: 'Personas' },
  { id: 'chats', label: 'Chats' },
  { id: 'uploads', label: 'Uploads' },
  { id: 'artefacts', label: 'Artefacts' },
  { id: 'images', label: 'Images' },
]

const FOCUSABLE =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function ProjectDetailOverlay({
  projectId,
  onClose,
  initialTab = 'overview',
}: ProjectDetailOverlayProps) {
  useBackButtonClose(true, onClose, 'project-overlay')
  const modalRef = useRef<HTMLDivElement>(null)

  const project = useProjectsStore((s) => s.projects[projectId])

  const [activeTab, setActiveTab] = useState<ProjectDetailTab>(initialTab)

  // Focus trap + Escape — mirrors PersonaOverlay verbatim.
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    modalRef.current?.focus()

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab') return

      const focusable = modalRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)
      if (!focusable || focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previousFocus?.focus()
    }
  }, [onClose])

  // The project might have been deleted out from under us (e.g.
  // another tab fired DELETE) — close gracefully rather than crashing.
  useEffect(() => {
    if (!project) onClose()
  }, [project, onClose])

  if (!project) return null

  const titleLabel = project.title || 'Untitled project'
  const emoji = project.emoji?.trim() || ''

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden
      />

      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Project: ${titleLabel}`}
        tabIndex={-1}
        data-testid="project-detail-overlay"
        className="absolute inset-0 lg:inset-4 z-20 flex flex-col rounded-none lg:rounded-xl shadow-2xl overflow-hidden outline-none border border-white/8 bg-surface"
      >
        {/* Header */}
        <div
          className="flex items-center justify-between border-b border-white/6 px-5 py-3 flex-shrink-0"
          style={{ paddingTop: 'max(0.75rem, env(safe-area-inset-top))' }}
        >
          <div className="flex min-w-0 items-center gap-2">
            <span aria-hidden="true" className="text-[16px] leading-none">
              {emoji || '—'}
            </span>
            <span className="truncate text-[13px] font-semibold text-white/85">
              {titleLabel}
            </span>
            {project.pinned && (
              <span className="flex-shrink-0 rounded border border-gold/35 bg-gold/10 px-1 py-[1px] font-mono text-[9px] uppercase tracking-wider text-gold/85">
                pinned
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close project overlay"
            title="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Tab bar */}
        <div
          role="tablist"
          aria-label="Project sections"
          className="flex flex-wrap gap-0.5 border-b border-white/6 px-3 flex-shrink-0 overflow-x-auto"
        >
          {TABS.map((tab) => {
            const selected = activeTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`project-tab-${tab.id}`}
                aria-selected={selected}
                aria-controls={`project-tabpanel-${tab.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => setActiveTab(tab.id)}
                className={[
                  'px-3 py-2 text-[12px] border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap',
                  selected
                    ? 'border-gold text-gold'
                    : 'border-transparent text-white/55 hover:text-white/80 hover:underline',
                ].join(' ')}
              >
                {tab.label}
              </button>
            )
          })}
        </div>

        {/* Tab content */}
        <div
          role="tabpanel"
          id={`project-tabpanel-${activeTab}`}
          aria-labelledby={`project-tab-${activeTab}`}
          className="flex-1 overflow-hidden flex flex-col"
        >
          {activeTab === 'overview' && (
            <ProjectOverviewTab projectId={projectId} />
          )}
          {activeTab === 'personas' && (
            <ProjectPersonasTab projectId={projectId} onClose={onClose} />
          )}
          {activeTab === 'chats' && (
            <HistoryTab onClose={onClose} projectFilter={projectId} />
          )}
          {activeTab === 'uploads' && (
            <UploadsTab projectFilter={projectId} />
          )}
          {activeTab === 'artefacts' && (
            <ArtefactsTab onClose={onClose} projectFilter={projectId} />
          )}
          {activeTab === 'images' && (
            <ImagesTab projectFilter={projectId} />
          )}
        </div>
      </div>
    </>
  )
}
