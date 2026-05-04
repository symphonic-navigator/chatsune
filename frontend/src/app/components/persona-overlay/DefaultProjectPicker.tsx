// Mindspace default-project picker for the persona Overview tab.
// Mirrors the chat-top-bar `ProjectPicker` content shape (search row +
// "— No default" + sorted, sanitised-filtered list) but talks to
// `personasApi.update` instead of `projectsApi.setSessionProject`.
//
// Lives next to `OverviewTab.tsx` rather than inside the projects
// feature folder because the call-site is persona-shaped: the picker
// patches a persona, with the project list as content. Reusing
// `ProjectPicker` directly would require widening it to a generic
// onChange callback, which adds API surface and noise where a thin
// dedicated component is easier to read.

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { personasApi } from '../../../core/api/personas'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { useSortedProjects } from '../../../features/projects/useProjectsStore'
import type { ProjectDto } from '../../../features/projects/types'

interface DefaultProjectPickerProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function DefaultProjectPicker({ persona, chakra }: DefaultProjectPickerProps) {
  const sortedProjects = useSortedProjects()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const addNotification = useNotificationStore((s) => s.addNotification)

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // The chip should reflect the currently-saved default even when that
  // project is NSFW and sanitised mode is on — the user's existing
  // choice stays visible. The picker list itself does respect
  // sanitised mode (mirrors §6.7 — sanitised filters discoverability,
  // not active state).
  const currentProject: ProjectDto | null = useMemo(() => {
    if (!persona.default_project_id) return null
    return sortedProjects.find((p) => p.id === persona.default_project_id) ?? null
  }, [sortedProjects, persona.default_project_id])

  const visibleProjects = useMemo(() => {
    const term = query.trim().toLowerCase()
    return sortedProjects
      .filter((p) => (isSanitised ? !p.nsfw : true))
      .filter((p) => (term ? p.title.toLowerCase().includes(term) : true))
  }, [sortedProjects, isSanitised, query])

  // Outside-click and Escape close the dropdown.
  useEffect(() => {
    if (!open) return
    function handleMouse(e: MouseEvent) {
      const node = containerRef.current
      if (!node) return
      if (!node.contains(e.target as Node)) setOpen(false)
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleMouse)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleMouse)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  async function assign(projectId: string | null) {
    if (busy) return
    setBusy(true)
    try {
      await personasApi.update(persona.id, { default_project_id: projectId })
      setOpen(false)
      setQuery('')
    } catch {
      addNotification({
        level: 'error',
        title: 'Update failed',
        message: 'Could not update the default project.',
      })
    } finally {
      setBusy(false)
    }
  }

  const chipEmoji = currentProject?.emoji ?? null
  const chipLabel = currentProject?.title ?? 'No default'

  return (
    <div className="w-full max-w-sm" ref={containerRef}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-mono uppercase tracking-wider text-white/45">
          Default project
        </span>
        <div className="relative">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            disabled={busy}
            data-testid="persona-default-project-trigger"
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-label={
              currentProject
                ? `Change default project (currently ${chipLabel})`
                : 'Set a default project'
            }
            className="flex items-center gap-1.5 rounded-md border border-white/10 bg-white/4 px-2 py-1 text-[12px] text-white/80 transition-colors hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ borderColor: `${chakra.hex}33` }}
          >
            <span aria-hidden="true" className="text-[14px] leading-none">
              {chipEmoji ?? '—'}
            </span>
            <span className="max-w-[160px] truncate">{chipLabel}</span>
            <span aria-hidden="true" className="text-[10px] text-white/55">▾</span>
          </button>

          {open && (
            <div
              role="listbox"
              aria-label="Default project"
              data-testid="persona-default-project-picker"
              className="absolute right-0 top-full z-50 mt-1.5 w-72 overflow-hidden rounded-md border border-white/10 bg-[#0f0d16] shadow-xl"
            >
              {/* "— No default" row */}
              <button
                type="button"
                role="option"
                aria-selected={!persona.default_project_id}
                disabled={busy}
                onClick={() => void assign(null)}
                data-testid="persona-default-project-clear"
                className={[
                  'flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] transition-colors',
                  !persona.default_project_id
                    ? 'bg-white/5 text-white/85'
                    : 'text-white/65 hover:bg-white/5 hover:text-white/85',
                ].join(' ')}
              >
                <span aria-hidden="true" className="text-[14px] leading-none">—</span>
                <span className="flex-1 truncate">No default</span>
              </button>

              {/* Search input */}
              <div className="border-y border-white/5 px-2 py-1.5">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search projects…"
                  autoFocus
                  data-testid="persona-default-project-search"
                  className="w-full rounded-md border border-white/6 bg-white/4 px-2 py-1 text-[12px] text-white/80 placeholder-white/35 outline-none transition-colors focus:border-white/12 focus:bg-white/6"
                />
              </div>

              {/* Project list */}
              <div className="max-h-64 overflow-y-auto py-1">
                {visibleProjects.length === 0 ? (
                  <p className="px-3 py-3 text-center text-[12px] text-white/45">
                    {query.trim() ? 'No matching projects' : 'No projects yet'}
                  </p>
                ) : (
                  visibleProjects.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      role="option"
                      aria-selected={persona.default_project_id === p.id}
                      disabled={busy}
                      onClick={() => void assign(p.id)}
                      data-testid={`persona-default-project-pick-${p.id}`}
                      className={[
                        'flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] transition-colors',
                        persona.default_project_id === p.id
                          ? 'bg-white/5 text-white/85'
                          : 'text-white/70 hover:bg-white/5 hover:text-white/90',
                      ].join(' ')}
                    >
                      <span aria-hidden="true" className="text-[14px] leading-none">
                        {p.emoji ?? '·'}
                      </span>
                      <span className="flex-1 truncate">{p.title}</span>
                      {p.pinned && (
                        <span aria-hidden="true" className="text-[11px] text-gold/70">
                          ★
                        </span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
