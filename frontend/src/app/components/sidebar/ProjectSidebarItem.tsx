import { PINNED_STRIPE_STYLE } from "./pinnedStripe"
import type { ProjectDto } from "../../../features/projects/types"

interface ProjectSidebarItemProps {
  project: ProjectDto
  /** Open the Project-Detail-Overlay (Phase 9). */
  onOpen: (projectId: string) => void
}

/**
 * One row in the sidebar Projects-zone. Mirrors `PersonaItem`'s visual
 * rhythm (avatar slot + name) so the three sidebar zones look
 * consistent. The avatar slot here is the project emoji (or a neutral
 * fallback dot) — projects don't carry a chakra colour-scheme.
 *
 * Phase 6 Task 25: this component is open-only. The hover-revealed
 * "···" menu and right-click / long-press context menu land in Task 26.
 */
export function ProjectSidebarItem({ project, onOpen }: ProjectSidebarItemProps) {
  const displayName = project.title || "Untitled project"
  const emoji = project.emoji?.trim() || ""

  return (
    <div
      className="group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1.5 transition-colors hover:bg-white/5"
      style={
        project.pinned
          ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' }
          : { paddingLeft: '8px', paddingRight: '8px' }
      }
      onClick={() => onOpen(project.id)}
    >
      <div
        className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-white/5 text-[12px]"
        aria-hidden="true"
      >
        {emoji || <span className="h-1.5 w-1.5 rounded-full bg-white/30" />}
      </div>

      <span className="min-w-0 flex-1 truncate text-[13px] text-white/50 transition-colors group-hover:text-white/75">
        {displayName}
      </span>
    </div>
  )
}
