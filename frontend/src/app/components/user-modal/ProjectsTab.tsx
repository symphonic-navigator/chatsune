// UserModal → Chats → Projects sub-tab. Spec §6.4: a flat list of the
// user's projects with client-side search, an optional pinned-only
// filter, and a "+ New Project" entry that mounts the existing
// ProjectCreateModal. Sanitised mode hides NSFW projects, mirroring the
// pattern already used by Sidebar.tsx, MobileProjectsView.tsx and
// ProjectPicker.tsx (Phase 11 will extract a shared
// ``filteredProjects`` helper; until then we replicate the inline
// filter pattern).
//
// Per-row click is a stub for the Phase-9 Project-Detail-Overlay —
// the row logs a single ``console.info`` line so the wiring point is
// obvious when Phase 9 lands.

import { useMemo, useState } from 'react'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { useSortedProjects } from '../../../features/projects/useProjectsStore'
import { ProjectCreateModal } from '../../../features/projects/ProjectCreateModal'
import { PINNED_STRIPE_STYLE } from '../sidebar/pinnedStripe'
import type { ProjectDto } from '../../../features/projects/types'

type ProjectFilter = 'all' | 'pinned'

function relativeTime(fromIso: string, now: number): string {
  const then = Date.parse(fromIso)
  if (Number.isNaN(then)) return ''
  const diffS = Math.max(0, Math.floor((now - then) / 1000))
  if (diffS < 60) return `${diffS}s ago`
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m ago`
  if (diffS < 86400) return `${Math.floor(diffS / 3600)}h ago`
  return `${Math.floor(diffS / 86400)}d ago`
}

export function ProjectsTab() {
  const projects = useSortedProjects()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ProjectFilter>('all')
  const [createOpen, setCreateOpen] = useState(false)

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase()
    return projects
      .filter((p) => (isSanitised ? !p.nsfw : true))
      .filter((p) => (filter === 'all' ? true : p.pinned))
      .filter((p) => (term ? p.title.toLowerCase().includes(term) : true))
  }, [projects, isSanitised, filter, query])

  // Stable "now" per render so every row formats against the same
  // reference point — keeps relative timestamps consistent within one
  // paint and makes tests deterministic.
  const now = Date.now()

  function handleOpenProject(id: string) {
    // TODO Phase 9: open Project-Detail-Overlay
    console.info('TODO Phase 9: open Project-Detail-Overlay', id)
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header: search + filter pill + "+ New" */}
      <div className="flex flex-shrink-0 flex-wrap items-center gap-2 px-4 pt-4 pb-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search projects…"
          aria-label="Search projects"
          className="min-w-0 flex-1 rounded-md border border-white/10 bg-white/4 px-3 py-1.5 text-[13px] text-white/85 placeholder-white/35 outline-none transition-colors focus:border-white/20 focus:bg-white/6"
        />

        {/* Filter pill: all / pinned only */}
        <div
          role="tablist"
          aria-label="Filter projects"
          className="flex items-center overflow-hidden rounded-md border border-white/10"
        >
          <FilterPill
            active={filter === 'all'}
            onClick={() => setFilter('all')}
            label="All"
          />
          <FilterPill
            active={filter === 'pinned'}
            onClick={() => setFilter('pinned')}
            label="Pinned only"
          />
        </div>

        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] font-medium text-white/70 transition-colors hover:bg-white/6 hover:text-white/90"
          aria-label="Create new project"
        >
          + New Project
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-4 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {visible.length === 0 ? (
          <EmptyState
            hasProjects={projects.length > 0}
            hasQuery={query.trim().length > 0 || filter !== 'all'}
          />
        ) : (
          <div className="flex flex-col gap-2">
            {visible.map((project) => (
              <ProjectRow
                key={project.id}
                project={project}
                now={now}
                onOpen={() => handleOpenProject(project.id)}
              />
            ))}
          </div>
        )}
      </div>

      {createOpen && (
        <ProjectCreateModal
          isOpen={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={() => setCreateOpen(false)}
        />
      )}
    </div>
  )
}

interface FilterPillProps {
  active: boolean
  onClick: () => void
  label: string
}

function FilterPill({ active, onClick, label }: FilterPillProps) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={[
        'px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors',
        active
          ? 'bg-gold/15 text-gold'
          : 'text-white/55 hover:bg-white/5 hover:text-white/80',
      ].join(' ')}
    >
      {label}
    </button>
  )
}

interface EmptyStateProps {
  hasProjects: boolean
  hasQuery: boolean
}

function EmptyState({ hasProjects, hasQuery }: EmptyStateProps) {
  if (hasProjects && hasQuery) {
    return (
      <div className="flex flex-col items-center justify-center gap-1 py-12 text-center">
        <p className="text-[13px] text-white/60">No matching projects</p>
        <p className="text-[11px] text-white/40">
          Try a different search or filter.
        </p>
      </div>
    )
  }
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <p className="text-[13px] text-white/60">No projects yet</p>
      <p className="max-w-xs text-[11px] leading-relaxed text-white/45">
        Projects let you group related personas, knowledge and chats
        together. Create your first one with "+ New Project".
      </p>
    </div>
  )
}

interface ProjectRowProps {
  project: ProjectDto
  now: number
  onOpen: () => void
}

function ProjectRow({ project, now, onOpen }: ProjectRowProps) {
  const displayName = project.title || 'Untitled project'
  const emoji = project.emoji?.trim() || ''
  const description = project.description?.trim() ?? ''
  const updatedLabel = relativeTime(project.updated_at, now)

  // The pinned stripe is a 3-px gold left border; padding compensates so
  // text aligns with unpinned rows. Mirrors PersonasTab/MobileProjectsView.
  const baseStyle: React.CSSProperties = {
    border: '1px solid rgba(255,255,255,0.06)',
  }
  const style: React.CSSProperties = project.pinned
    ? { ...baseStyle, ...PINNED_STRIPE_STYLE }
    : baseStyle

  return (
    <button
      type="button"
      data-testid="project-row"
      data-project-id={project.id}
      onClick={onOpen}
      className="flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/5"
      style={style}
    >
      <span
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-white/5 text-[18px]"
        aria-hidden="true"
      >
        {emoji || <span className="text-white/35">—</span>}
      </span>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-semibold text-white/90">
            {displayName}
          </span>
          {project.pinned && (
            <span
              data-testid="project-pinned-badge"
              className="flex-shrink-0 rounded border border-gold/35 bg-gold/10 px-1 py-[1px] font-mono text-[9px] uppercase tracking-wider text-gold/85"
            >
              pinned
            </span>
          )}
          {updatedLabel && (
            <span className="ml-auto flex-shrink-0 font-mono text-[10px] text-white/40">
              updated {updatedLabel}
            </span>
          )}
        </div>
        {description && (
          <span className="mt-0.5 line-clamp-2 text-[12px] text-white/55">
            {description}
          </span>
        )}
      </div>
    </button>
  )
}
