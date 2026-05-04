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
import { useProjectOverlayStore } from './useProjectOverlayStore'
import { ProjectPicker } from './ProjectPicker'
import { ProjectPickerMobile } from './ProjectPickerMobile'

interface ProjectSwitcherProps {
  sessionId: string
  currentProjectId: string | null
  /**
   * Optional override for the ``[emoji][title]`` chip click. The
   * default opens the Project-Detail-Overlay via the shared overlay
   * store; tests pass an explicit handler to assert click-through
   * without mounting the global overlay.
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
  const openProjectOverlay = useProjectOverlayStore((s) => s.open)
  const [pickerOpen, setPickerOpen] = useState(false)
  const { isDesktop } = useViewport()
  const effectiveOpenDetail =
    onOpenDetail ?? ((projectId: string) => openProjectOverlay(projectId))

  const emoji = project?.emoji ?? null
  const title = project?.title ?? null
  const hasProject = !!project

  const chipLabel = hasProject ? title ?? 'Untitled project' : 'No project'
  const chipEmoji = hasProject ? emoji ?? '' : '—'

  // The detail chip is disabled only when no project is assigned;
  // when a project IS assigned, the default handler always opens the
  // overlay store, so the chip is always actionable in that case.
  const detailDisabled = !hasProject
  const detailTitle = hasProject ? `Open ${chipLabel}` : 'No project assigned'

  return (
    <div className="relative flex items-center gap-1">
      <button
        type="button"
        disabled={detailDisabled}
        onClick={() => {
          if (project) effectiveOpenDetail(project.id)
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
