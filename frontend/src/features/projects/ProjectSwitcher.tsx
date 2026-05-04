// In-chat project switcher. Lives in the right-hand side of the chat
// top-bar and gives the user two affordances:
//
//   1. ``[emoji][title]`` — a button that opens the Project-Detail-
//      Overlay for the assigned project (Phase 9). Disabled when the
//      session has no project (the chip falls back to ``[—]`` ``[No
//      project]``).
//   2. ``[▾]`` — a dropdown trigger that opens the project picker. On
//      desktop the picker is a small inline dropdown; on mobile it
//      takes over the full screen, mirroring the "Start new chat"
//      mobile flow.
//
// The component is purely presentational over `useProjectsStore` —
// the source of truth for the assigned ``project_id`` lives one level
// up (in the chat-sessions store) and is forwarded as a prop. That
// keeps the switcher trivial to test and avoids a second event-bus
// subscription that would duplicate work `useChatSessions` already
// does.

import { useState } from 'react'
import { useViewport } from '../../core/hooks/useViewport'
import { useProjectsStore } from './useProjectsStore'
import { ProjectPicker } from './ProjectPicker'
import { ProjectPickerMobile } from './ProjectPickerMobile'

interface ProjectSwitcherProps {
  sessionId: string
  currentProjectId: string | null
  /**
   * Phase 9 hook — invoked when the ``[emoji][title]`` chip is clicked
   * for an assigned project. Stubbed at the parent until the detail
   * overlay lands; the chip is rendered as a visually-disabled
   * non-button when the callback is omitted.
   */
  onOpenDetail?: (projectId: string) => void
}

export function ProjectSwitcher({
  sessionId,
  currentProjectId,
  onOpenDetail,
}: ProjectSwitcherProps) {
  const project = useProjectsStore((s) =>
    currentProjectId ? s.projects[currentProjectId] : null,
  )
  const [pickerOpen, setPickerOpen] = useState(false)
  const { isDesktop } = useViewport()

  const emoji = project?.emoji ?? null
  const title = project?.title ?? null
  const hasProject = !!project

  const chipLabel = hasProject ? title ?? 'Untitled project' : 'No project'
  const chipEmoji = hasProject ? emoji ?? '' : '—'

  const detailDisabled = !hasProject || !onOpenDetail
  const detailTitle = hasProject ? `Open ${chipLabel}` : 'No project assigned'

  return (
    <div className="relative flex items-center gap-1">
      <button
        type="button"
        disabled={detailDisabled}
        onClick={() => {
          if (project && onOpenDetail) onOpenDetail(project.id)
        }}
        title={detailTitle}
        aria-label={detailTitle}
        className={[
          'flex items-center gap-1.5 rounded-md border border-white/8 bg-white/4 px-2 py-1 text-[12px] transition-colors',
          detailDisabled
            ? 'cursor-default text-white/40'
            : 'cursor-pointer text-white/75 hover:bg-white/8',
        ].join(' ')}
      >
        <span aria-hidden="true" className="text-[14px] leading-none">
          {chipEmoji || '—'}
        </span>
        <span className="max-w-[160px] truncate">{chipLabel}</span>
      </button>
      <button
        type="button"
        onClick={() => setPickerOpen((v) => !v)}
        title={pickerOpen ? 'Close project picker' : 'Switch project'}
        aria-label={pickerOpen ? 'Close project picker' : 'Switch project'}
        aria-expanded={pickerOpen}
        aria-haspopup="listbox"
        className={[
          'flex h-7 w-6 items-center justify-center rounded-md border border-white/8 bg-white/4 text-[12px] transition-colors',
          pickerOpen
            ? 'bg-white/10 text-white/80'
            : 'text-white/55 hover:bg-white/8 hover:text-white/80',
        ].join(' ')}
      >
        <span aria-hidden="true">▾</span>
      </button>

      {pickerOpen && (isDesktop ? (
        <ProjectPicker
          sessionId={sessionId}
          currentProjectId={currentProjectId}
          onClose={() => setPickerOpen(false)}
        />
      ) : (
        <ProjectPickerMobile
          sessionId={sessionId}
          currentProjectId={currentProjectId}
          onClose={() => setPickerOpen(false)}
        />
      ))}
    </div>
  )
}
