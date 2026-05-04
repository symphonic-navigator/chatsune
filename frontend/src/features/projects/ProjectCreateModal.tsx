// ProjectCreateModal — stub introduced in Task 29 so the
// ProjectPicker type-checks; full implementation lands in Task 31.

import type { ProjectDto } from './types'

export interface ProjectCreateModalProps {
  isOpen: boolean
  onClose: () => void
  onCreated: (project: ProjectDto) => void
}

export function ProjectCreateModal(_props: ProjectCreateModalProps) {
  return null
}
