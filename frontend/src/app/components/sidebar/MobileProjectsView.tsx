import type { ProjectDto } from '../../../features/projects/types'
import { useFilteredProjects } from '../../../features/projects/useProjectsStore'
import { PINNED_STRIPE_STYLE } from './pinnedStripe'

interface MobileProjectsViewProps {
  /** Tap-handler for a project row. Receives the project's id. */
  onSelect: (projectId: string) => void
}

/**
 * Mobile second-panel content for the sidebar Projects entry. Lists
 * `useFilteredProjects()` (sanitised-aware) so NSFW projects disappear
 * in sanitised mode without per-call-site filtering. Tapping a row
 * delegates to `onSelect`, which the sidebar host wires to the
 * Project-Detail-Overlay via `useProjectOverlayStore` (Phase 9).
 *
 * Layout mirrors `MobileNewChatView`'s row rhythm so the two
 * second-panel screens feel of-a-piece. Unlike personas, projects
 * don't carry chakra colours — the avatar slot shows the project
 * emoji or a neutral fallback.
 */
export function MobileProjectsView({ onSelect }: MobileProjectsViewProps) {
  const visible = useFilteredProjects()

  if (visible.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
        <p className="text-[14px] text-white/60">No projects yet</p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto py-1 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {visible.map((p) => (
          <ProjectRow key={p.id} project={p} onSelect={onSelect} />
        ))}
      </div>
    </div>
  )
}

interface ProjectRowProps {
  project: ProjectDto
  onSelect: (projectId: string) => void
}

function ProjectRow({ project, onSelect }: ProjectRowProps) {
  const displayName = project.title || 'Untitled project'
  const emoji = project.emoji?.trim() || ''

  return (
    <button
      type="button"
      onClick={() => onSelect(project.id)}
      className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-white/4"
      style={
        project.pinned
          ? { ...PINNED_STRIPE_STYLE, paddingLeft: '11px' }
          : undefined
      }
    >
      <span
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-white/5 text-[16px]"
        aria-hidden="true"
      >
        {emoji || <span className="h-2 w-2 rounded-full bg-white/30" />}
      </span>
      <span className="flex-1 truncate text-[14px] text-white/85">{displayName}</span>
      {project.nsfw && (
        <span className="flex-shrink-0 rounded-full border border-pink-400/35 bg-pink-400/15 px-1.5 py-[1px] text-[9px] font-semibold uppercase tracking-wider text-pink-200/90">
          NSFW
        </span>
      )}
    </button>
  )
}
