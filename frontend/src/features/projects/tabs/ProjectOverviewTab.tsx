// Project-Detail-Overlay — Overview tab (spec §6.5 Tab 1).
//
// Fields: emoji (with picker), name (inline-edit, save on blur),
// description (inline-edit, save on blur), NSFW toggle (immediate),
// knowledge libraries multi-select. The Danger-Zone "Delete Project"
// button mounts the DeleteProjectModal (Phase 12 / spec §9).
//
// All mutations go through `projectsApi.patch`; the
// `PROJECT_UPDATED` WebSocket event then re-flows into
// `useProjectsStore` and re-renders this component. Local form
// state mirrors the store so an in-flight edit isn't clobbered by an
// echo of our own PATCH — we only re-seed when the underlying field
// changes AND the user isn't currently editing it.

import { useEffect, useRef, useState } from 'react'
import { useKnowledgeStore } from '../../../core/store/knowledgeStore'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { KissMarkIcon } from '../../../core/components/symbols'
import { useProjectsStore } from '../useProjectsStore'
import { useRecentProjectEmojisStore } from '../recentProjectEmojisStore'
import { projectsApi } from '../projectsApi'
import { DeleteProjectModal } from '../DeleteProjectModal'
import { EmojiPickerPopover } from '../../chat/EmojiPickerPopover'

interface ProjectOverviewTabProps {
  projectId: string
}

const MAX_NAME_LENGTH = 80
const MAX_DESCRIPTION_LENGTH = 2000

export function ProjectOverviewTab({ projectId }: ProjectOverviewTabProps) {
  const project = useProjectsStore((s) => s.projects[projectId])
  const addNotification = useNotificationStore((s) => s.addNotification)
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const libraries = useKnowledgeStore((s) => s.libraries)
  const fetchLibraries = useKnowledgeStore((s) => s.fetchLibraries)
  const recentProjectEmojis = useRecentProjectEmojisStore((s) => s.emojis)

  // Local edit state for inline-edit fields. Seeded from the project
  // on mount and re-seeded when the backing project mutates externally
  // (e.g. another tab made an edit) — but only when the user isn't
  // actively editing that field.
  const [name, setName] = useState(project?.title ?? '')
  const [description, setDescription] = useState(project?.description ?? '')
  const [editingName, setEditingName] = useState(false)
  const [editingDescription, setEditingDescription] = useState(false)
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false)
  const [libDropdownOpen, setLibDropdownOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const libDropdownRef = useRef<HTMLDivElement>(null)
  const emojiButtonRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void fetchLibraries()
  }, [fetchLibraries])

  // Re-seed local form state when the underlying project changes
  // externally — but never while the user is actively editing.
  useEffect(() => {
    if (!project) return
    if (!editingName) setName(project.title)
    if (!editingDescription) setDescription(project.description ?? '')
  }, [project, editingName, editingDescription])

  // Close the library-picker dropdown on outside click.
  useEffect(() => {
    if (!libDropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (libDropdownRef.current && !libDropdownRef.current.contains(e.target as Node)) {
        setLibDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [libDropdownOpen])

  if (!project) return null

  const assignedIds = project.knowledge_library_ids
  const assignedLibraries = libraries.filter((l) => assignedIds.includes(l.id))
  const unassignedLibraries = libraries.filter((l) => !assignedIds.includes(l.id))
  const visibleUnassigned = isSanitised
    ? unassignedLibraries.filter((l) => !l.nsfw)
    : unassignedLibraries
  const visibleAssigned = isSanitised
    ? assignedLibraries.filter((l) => !l.nsfw)
    : assignedLibraries
  const hasNsfwLibraries = libraries.some((l) => l.nsfw)

  async function patch(body: Parameters<typeof projectsApi.patch>[1]) {
    try {
      await projectsApi.patch(projectId, body)
    } catch {
      addNotification({
        level: 'error',
        title: 'Update failed',
        message: 'Could not save the change.',
      })
    }
  }

  async function handleEmojiSelect(picked: string) {
    setEmojiPickerOpen(false)
    if (project && picked === project.emoji) return
    await patch({ emoji: picked })
    // Push to the recent-emoji LRU. The store mirrors the
    // server-side ``recent_project_emojis`` field; the backend
    // currently doesn't emit a topic on PATCH but we keep the local
    // bump so the picker surfaces it next time.
    const next = [picked, ...recentProjectEmojis.filter((e) => e !== picked)].slice(0, 32)
    useRecentProjectEmojisStore.getState().set(next)
  }

  async function handleNameBlur() {
    setEditingName(false)
    const trimmed = name.trim()
    if (!trimmed) {
      // Empty is invalid — revert.
      setName(project?.title ?? '')
      addNotification({
        level: 'warning',
        title: 'Name required',
        message: 'Project name cannot be empty.',
      })
      return
    }
    if (trimmed === project?.title) return
    if (trimmed.length > MAX_NAME_LENGTH) {
      addNotification({
        level: 'warning',
        title: 'Name too long',
        message: `Names must be ${MAX_NAME_LENGTH} characters or fewer.`,
      })
      setName(project?.title ?? '')
      return
    }
    await patch({ title: trimmed })
  }

  async function handleDescriptionBlur() {
    setEditingDescription(false)
    const trimmed = description.trim()
    const current = project?.description ?? ''
    if (trimmed === current) return
    if (trimmed.length > MAX_DESCRIPTION_LENGTH) {
      addNotification({
        level: 'warning',
        title: 'Description too long',
        message: `Descriptions must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`,
      })
      setDescription(current)
      return
    }
    await patch({ description: trimmed === '' ? null : trimmed })
  }

  async function handleNsfwToggle() {
    await patch({ nsfw: !project.nsfw })
  }

  async function handleAssignLibrary(libraryId: string) {
    setLibDropdownOpen(false)
    if (assignedIds.includes(libraryId)) return
    await patch({ knowledge_library_ids: [...assignedIds, libraryId] })
  }

  async function handleRemoveLibrary(libraryId: string) {
    if (!assignedIds.includes(libraryId)) return
    await patch({
      knowledge_library_ids: assignedIds.filter((id) => id !== libraryId),
    })
  }

  function handleDelete() {
    setDeleteOpen(true)
  }

  return (
    <div className="flex-1 overflow-y-auto p-6" data-testid="project-overview-tab">
      <div className="mx-auto flex max-w-3xl flex-col gap-6">
        {/* Emoji + Name row */}
        <div className="flex items-end gap-3">
          <div ref={emojiButtonRef} className="relative">
            <label className="mb-1 block text-[11px] font-mono uppercase tracking-wider text-white/45">
              Emoji
            </label>
            <button
              type="button"
              onClick={() => setEmojiPickerOpen((v) => !v)}
              aria-label={project.emoji ? `Change emoji (${project.emoji})` : 'Add emoji'}
              data-testid="project-overview-emoji"
              className="flex h-12 w-12 items-center justify-center rounded-md border border-white/10 bg-white/4 text-[24px] transition-colors hover:bg-white/8"
            >
              {project.emoji ?? <span className="text-[18px] text-white/35">+</span>}
            </button>
            {emojiPickerOpen && (
              <EmojiPickerPopover
                onSelect={(picked) => void handleEmojiSelect(picked)}
                onClose={() => setEmojiPickerOpen(false)}
                recentEmojis={recentProjectEmojis}
                overlay
              />
            )}
          </div>

          <div className="flex flex-1 flex-col">
            <label
              htmlFor="project-overview-name"
              className="mb-1 text-[11px] font-mono uppercase tracking-wider text-white/45"
            >
              Project name
            </label>
            <input
              id="project-overview-name"
              type="text"
              value={name}
              maxLength={MAX_NAME_LENGTH}
              onChange={(e) => setName(e.target.value)}
              onFocus={() => setEditingName(true)}
              onBlur={() => void handleNameBlur()}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  ;(e.target as HTMLInputElement).blur()
                }
                if (e.key === 'Escape') {
                  setName(project.title)
                  setEditingName(false)
                  ;(e.target as HTMLInputElement).blur()
                }
              }}
              data-testid="project-overview-name"
              className="rounded-md border border-white/10 bg-white/4 px-3 py-2 text-[16px] font-semibold text-white/90 outline-none transition-colors focus:border-white/20 focus:bg-white/6"
            />
          </div>
        </div>

        {/* Description */}
        <div className="flex flex-col">
          <label
            htmlFor="project-overview-description"
            className="mb-1 text-[11px] font-mono uppercase tracking-wider text-white/45"
          >
            Description
          </label>
          <textarea
            id="project-overview-description"
            value={description}
            rows={3}
            maxLength={MAX_DESCRIPTION_LENGTH}
            onChange={(e) => setDescription(e.target.value)}
            onFocus={() => setEditingDescription(true)}
            onBlur={() => void handleDescriptionBlur()}
            placeholder="Optional — what is this project about?"
            data-testid="project-overview-description"
            className="resize-none rounded-md border border-white/10 bg-white/4 px-3 py-2 text-[13px] text-white/85 placeholder-white/35 outline-none transition-colors focus:border-white/20 focus:bg-white/6"
          />
        </div>

        {/* NSFW */}
        <div className="flex items-center justify-between rounded-md border border-white/8 bg-white/2 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium text-white/85">NSFW</span>
            <KissMarkIcon />
            <span className="text-[11px] text-white/40">
              Hide this project when sanitised mode is on.
            </span>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={project.nsfw}
            aria-label="Toggle NSFW"
            onClick={() => void handleNsfwToggle()}
            data-testid="project-overview-nsfw"
            className={[
              'rounded border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors',
              project.nsfw
                ? 'border-gold/40 bg-gold/15 text-gold'
                : 'border-white/10 text-white/55 hover:bg-white/6',
            ].join(' ')}
          >
            {project.nsfw ? '✓ on' : '✕ off'}
          </button>
        </div>

        {/* Knowledge libraries */}
        <div className="flex flex-col gap-2">
          <span className="text-[11px] font-mono uppercase tracking-wider text-white/45">
            Knowledge libraries
          </span>
          {visibleAssigned.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {visibleAssigned.map((lib) => (
                <span
                  key={lib.id}
                  data-testid={`project-overview-library-${lib.id}`}
                  className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/4 px-2 py-1 text-[12px] text-white/85"
                >
                  <span className="truncate">{lib.name}</span>
                  {lib.nsfw && (
                    <span aria-hidden="true">
                      <KissMarkIcon />
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleRemoveLibrary(lib.id)}
                    aria-label={`Remove ${lib.name}`}
                    className="text-white/45 hover:text-white/85"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-white/45">
              No libraries assigned to this project yet.
            </p>
          )}

          <div className="relative" ref={libDropdownRef}>
            <button
              type="button"
              onClick={() => setLibDropdownOpen((v) => !v)}
              data-testid="project-overview-add-library"
              className="rounded-md border border-dashed border-white/15 px-2.5 py-1.5 text-[12px] text-white/65 transition-colors hover:border-white/25 hover:text-white/85"
            >
              + Add library…
            </button>
            {libDropdownOpen && (
              <div
                role="listbox"
                aria-label="Add knowledge library"
                className="absolute left-0 top-full mt-1 z-10 w-72 max-h-72 overflow-y-auto rounded-md border border-white/10 bg-[#0f0d16] shadow-xl"
              >
                {visibleUnassigned.length === 0 ? (
                  <p className="px-3 py-2 text-[12px] text-white/45">
                    No more libraries available.
                  </p>
                ) : (
                  visibleUnassigned.map((lib) => (
                    <button
                      key={lib.id}
                      type="button"
                      role="option"
                      aria-selected={false}
                      onClick={() => void handleAssignLibrary(lib.id)}
                      data-testid={`project-overview-add-library-${lib.id}`}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] text-white/80 transition-colors hover:bg-white/6"
                    >
                      <span className="flex-1 truncate">{lib.name}</span>
                      <span className="shrink-0 text-[11px] text-white/45">
                        {lib.document_count} doc
                        {lib.document_count === 1 ? '' : 's'}
                      </span>
                      {lib.nsfw && (
                        <span aria-hidden="true">
                          <KissMarkIcon />
                        </span>
                      )}
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
          {hasNsfwLibraries && !isSanitised && (
            <p className="font-mono text-[11px] text-white/55 inline-flex items-center gap-1">
              <KissMarkIcon /> libraries are hidden when sanitised mode is active
            </p>
          )}
        </div>

        {/* Danger Zone */}
        <div
          className="mt-4 flex flex-col gap-2 rounded-md border border-red-400/25 bg-red-400/5 p-4"
          data-testid="project-overview-danger-zone"
        >
          <span className="text-[11px] font-mono uppercase tracking-wider text-red-300/85">
            Danger zone
          </span>
          <p className="text-[12px] text-white/65">
            Deleting a project removes the project itself. You can choose
            whether to keep or purge member chats, uploads, artefacts and
            images at delete time.
          </p>
          <div>
            <button
              type="button"
              onClick={handleDelete}
              data-testid="project-overview-delete"
              className="rounded border border-red-400/35 bg-red-400/10 px-3 py-1.5 text-[12px] font-mono uppercase tracking-wider text-red-300 transition-colors hover:bg-red-400/15"
            >
              Delete project
            </button>
          </div>
        </div>
      </div>

      {deleteOpen && (
        <DeleteProjectModal
          isOpen={deleteOpen}
          projectId={projectId}
          projectTitle={project.title}
          onClose={() => setDeleteOpen(false)}
        />
      )}
    </div>
  )
}
