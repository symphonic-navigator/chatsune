// Project-Detail-Overlay — Personas tab (spec §6.5 Tab 2).
//
// Stub: filled in by Task 35 of Phase 9. The shell mounts this so the
// overlay tests can switch tabs deterministically.

interface ProjectPersonasTabProps {
  projectId: string
  onClose: () => void
}

export function ProjectPersonasTab({ projectId }: ProjectPersonasTabProps) {
  return (
    <div
      data-testid="project-personas-tab"
      className="flex-1 overflow-y-auto p-6 text-[12px] text-white/40"
    >
      Personas tab — {projectId}
    </div>
  )
}
