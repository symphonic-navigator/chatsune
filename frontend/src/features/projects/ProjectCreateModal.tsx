// ProjectCreateModal — single uniform form per spec §6.4: every
// field except the project name is optional. Reuses the existing
// ``Sheet`` overlay so the modal infrastructure (portal, backdrop,
// Esc-to-close, body-scroll-lock) is the same as every other
// modal in the app.
//
// Library multi-select is rendered inline rather than reusing the
// persona-overlay KnowledgeTab — that component is bound to a
// persona document and assigns libraries via a dedicated API call.
// For project creation we just collect ids in local state and
// hand them to ``projectsApi.create`` in the submit body, so an
// inline checkbox list is the simpler fit. (Per the brief: "if
// reusing is awkward, render a minimal inline multi-select".)

import { useEffect, useMemo, useRef, useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { useKnowledgeStore } from '../../core/store/knowledgeStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { useSanitisedMode } from '../../core/store/sanitisedModeStore'
import { EmojiPickerPopover } from '../chat/EmojiPickerPopover'
import { KissMarkIcon } from '../../core/components/symbols'
import { projectsApi } from './projectsApi'
import { useRecentProjectEmojisStore } from './recentProjectEmojisStore'
import type { ProjectDto } from './types'

const MAX_NAME_LENGTH = 80

export interface ProjectCreateModalProps {
  isOpen: boolean
  onClose: () => void
  onCreated: (project: ProjectDto) => void
}

export function ProjectCreateModal({
  isOpen,
  onClose,
  onCreated,
}: ProjectCreateModalProps) {
  const addNotification = useNotificationStore((s) => s.addNotification)
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const libraries = useKnowledgeStore((s) => s.libraries)
  const fetchLibraries = useKnowledgeStore((s) => s.fetchLibraries)

  const recentProjectEmojis = useRecentProjectEmojisStore((s) => s.emojis)

  const [name, setName] = useState('')
  const [emoji, setEmoji] = useState<string | null>(null)
  const [description, setDescription] = useState('')
  const [nsfw, setNsfw] = useState(false)
  const [libraryIds, setLibraryIds] = useState<string[]>([])
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const nameInputRef = useRef<HTMLInputElement>(null)
  const emojiButtonRef = useRef<HTMLDivElement>(null)

  // Reset form state every time the modal opens so a previous
  // discarded input doesn't leak into the next session.
  useEffect(() => {
    if (!isOpen) return
    setName('')
    setEmoji(null)
    setDescription('')
    setNsfw(false)
    setLibraryIds([])
    setEmojiPickerOpen(false)
    setSubmitting(false)
    void fetchLibraries()
    // Defer one frame so the dialog is mounted before focusing.
    requestAnimationFrame(() => nameInputRef.current?.focus())
  }, [isOpen, fetchLibraries])

  const visibleLibraries = useMemo(
    () => (isSanitised ? libraries.filter((l) => !l.nsfw) : libraries),
    [libraries, isSanitised],
  )

  const trimmedName = name.trim()
  const isNameValid =
    trimmedName.length >= 1 && trimmedName.length <= MAX_NAME_LENGTH
  const canSubmit = isNameValid && !submitting

  function toggleLibrary(libraryId: string) {
    setLibraryIds((prev) =>
      prev.includes(libraryId)
        ? prev.filter((id) => id !== libraryId)
        : [...prev, libraryId],
    )
  }

  async function handleSubmit() {
    if (!canSubmit) return
    setSubmitting(true)
    try {
      const created = await projectsApi.create({
        title: trimmedName,
        emoji: emoji ?? null,
        description: description.trim() ? description.trim() : null,
        nsfw,
        knowledge_library_ids: libraryIds,
      })
      onCreated(created)
    } catch {
      addNotification({
        level: 'error',
        title: 'Create failed',
        message: 'Could not create the project.',
      })
      setSubmitting(false)
    }
  }

  function handleEmojiSelect(picked: string) {
    setEmoji(picked)
    setEmojiPickerOpen(false)
  }

  return (
    <Sheet
      isOpen={isOpen}
      onClose={submitting ? () => {} : onClose}
      size="md"
      ariaLabel="Create new project"
      className="border border-white/8 bg-elevated shadow-2xl"
    >
      <div className="flex flex-col">
        {/* Header */}
        <div className="border-b border-white/6 px-5 py-4">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            New project
          </h2>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-4 overflow-y-auto px-5 py-4">
          {/* Name + emoji row */}
          <div className="flex items-end gap-2">
            {/* Emoji picker */}
            <div ref={emojiButtonRef} className="relative">
              <label className="mb-1 block text-[11px] font-mono uppercase tracking-wider text-white/45">
                Emoji
              </label>
              <button
                type="button"
                onClick={() => setEmojiPickerOpen((v) => !v)}
                aria-label={emoji ? `Change emoji (${emoji})` : 'Add emoji'}
                className="flex h-9 w-9 items-center justify-center rounded-md border border-white/10 bg-white/4 text-[18px] transition-colors hover:bg-white/8"
              >
                {emoji ?? (
                  <span className="text-[16px] text-white/35">+</span>
                )}
              </button>
              {emojiPickerOpen && (
                <EmojiPickerPopover
                  onSelect={handleEmojiSelect}
                  onClose={() => setEmojiPickerOpen(false)}
                  recentEmojis={recentProjectEmojis}
                  overlay
                />
              )}
            </div>

            {/* Name */}
            <div className="flex flex-1 flex-col">
              <label
                htmlFor="project-create-name"
                className="mb-1 text-[11px] font-mono uppercase tracking-wider text-white/45"
              >
                Name<span className="text-red-400">*</span>
              </label>
              <input
                id="project-create-name"
                ref={nameInputRef}
                type="text"
                value={name}
                maxLength={MAX_NAME_LENGTH}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && canSubmit) {
                    e.preventDefault()
                    void handleSubmit()
                  }
                }}
                placeholder="e.g. Star Trek Fan Fiction"
                className="rounded-md border border-white/10 bg-white/4 px-3 py-2 text-[13px] text-white/90 placeholder-white/35 outline-none transition-colors focus:border-white/20 focus:bg-white/6"
              />
            </div>
          </div>

          {/* Description */}
          <div className="flex flex-col">
            <label
              htmlFor="project-create-description"
              className="mb-1 text-[11px] font-mono uppercase tracking-wider text-white/45"
            >
              Description
            </label>
            <textarea
              id="project-create-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Optional — what is this project about?"
              className="resize-none rounded-md border border-white/10 bg-white/4 px-3 py-2 text-[13px] text-white/85 placeholder-white/35 outline-none transition-colors focus:border-white/20 focus:bg-white/6"
            />
          </div>

          {/* NSFW toggle */}
          <label className="flex cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              checked={nsfw}
              onChange={(e) => setNsfw(e.target.checked)}
              className="h-3.5 w-3.5 cursor-pointer"
              data-testid="project-create-nsfw"
            />
            <span className="flex items-center gap-1.5 text-[12px] text-white/75">
              NSFW <KissMarkIcon />
            </span>
            <span className="text-[11px] text-white/40">
              Hide this project when sanitised mode is on.
            </span>
          </label>

          {/* Knowledge libraries */}
          <div className="flex flex-col">
            <span className="mb-1 text-[11px] font-mono uppercase tracking-wider text-white/45">
              Knowledge libraries
            </span>
            {visibleLibraries.length === 0 ? (
              <p className="text-[12px] text-white/45">
                No knowledge libraries available.
              </p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {visibleLibraries.map((lib) => {
                  const checked = libraryIds.includes(lib.id)
                  return (
                    <label
                      key={lib.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md border border-white/6 bg-white/3 px-2.5 py-1.5 transition-colors hover:bg-white/6"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleLibrary(lib.id)}
                        className="h-3.5 w-3.5 cursor-pointer"
                        data-testid={`project-create-library-${lib.id}`}
                      />
                      <span className="flex-1 truncate text-[13px] text-white/85">
                        {lib.name}
                      </span>
                      <span className="text-[11px] text-white/40">
                        {lib.document_count} doc
                        {lib.document_count === 1 ? '' : 's'}
                      </span>
                      {lib.nsfw && (
                        <span className="shrink-0">
                          <KissMarkIcon />
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-white/6 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded border border-white/8 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/60 transition-colors hover:border-white/15 hover:text-white/80 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
            className="rounded border border-gold/40 bg-gold/15 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors hover:bg-gold/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
