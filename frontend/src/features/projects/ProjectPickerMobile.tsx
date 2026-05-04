// Mobile project picker — stub introduced in Task 28 so the
// ProjectSwitcher type-checks; full implementation lands in Task 30.

interface ProjectPickerMobileProps {
  sessionId: string
  currentProjectId: string | null
  onClose: () => void
}

export function ProjectPickerMobile(_props: ProjectPickerMobileProps) {
  return null
}
