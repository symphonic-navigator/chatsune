// Desktop project picker — stub introduced in Task 28 so the
// ProjectSwitcher type-checks; full implementation lands in Task 29.

interface ProjectPickerProps {
  sessionId: string
  currentProjectId: string | null
  onClose: () => void
}

export function ProjectPicker(_props: ProjectPickerProps) {
  return null
}
