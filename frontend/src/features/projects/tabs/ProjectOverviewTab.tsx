// Project-Detail-Overlay — Overview tab (spec §6.5 Tab 1).
//
// Stub: filled in by Task 34 of Phase 9. The shell mounts this so the
// overlay tests can switch tabs deterministically.

interface ProjectOverviewTabProps {
  projectId: string
}

export function ProjectOverviewTab({ projectId }: ProjectOverviewTabProps) {
  return (
    <div
      data-testid="project-overview-tab"
      className="flex-1 overflow-y-auto p-6 text-[12px] text-white/40"
    >
      Overview tab — {projectId}
    </div>
  )
}
