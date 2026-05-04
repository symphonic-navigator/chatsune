// Project-Detail-Overlay — Personas tab (spec §6.5 Tab 2).
//
// Lists every persona whose ``default_project_id`` matches this
// project. Each row exposes:
//   - "Start chat here" — creates a new session against the persona,
//     attaches it to this project, navigates into it.
//   - "Remove from project" — clears the persona's default-project
//     pointer (a PATCH that nulls ``default_project_id``).
//
// "+ Add persona" mounts a small searchable picker over every
// persona the user owns. Sanitised mode hides NSFW personas in the
// picker (consistent with the rest of the app); the in-list
// rendering above is deliberately *not* filtered — a persona that
// already has this project as its default is established intent and
// stays visible.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { chatApi } from '../../../core/api/chat'
import { useProjectsStore } from '../useProjectsStore'

interface ProjectPersonasTabProps {
  projectId: string
  onClose: () => void
}

export function ProjectPersonasTab({ projectId, onClose }: ProjectPersonasTabProps) {
  const { personas, update: updatePersona } = usePersonas()
  const projects = useProjectsStore((s) => s.projects)
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const addNotification = useNotificationStore((s) => s.addNotification)
  const navigate = useNavigate()

  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerQuery, setPickerQuery] = useState('')
  const [pendingSwitch, setPendingSwitch] = useState<{
    persona: PersonaDto
    fromProjectTitle: string
  } | null>(null)
  const [busy, setBusy] = useState(false)

  const pickerRef = useRef<HTMLDivElement>(null)

  // Close picker on outside click.
  useEffect(() => {
    if (!pickerOpen) return
    const handler = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [pickerOpen])

  // Close picker on Escape.
  useEffect(() => {
    if (!pickerOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPickerOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [pickerOpen])

  const inProject = useMemo(
    () =>
      personas
        .filter((p) => p.default_project_id === projectId)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [personas, projectId],
  )

  const pickerCandidates = useMemo(() => {
    const term = pickerQuery.trim().toLowerCase()
    return personas
      .filter((p) => p.default_project_id !== projectId)
      .filter((p) => (isSanitised ? !p.nsfw : true))
      .filter((p) =>
        term
          ? p.name.toLowerCase().includes(term) ||
            (p.tagline ?? '').toLowerCase().includes(term)
          : true,
      )
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [personas, projectId, isSanitised, pickerQuery])

  async function handleStartChat(persona: PersonaDto) {
    setBusy(true)
    try {
      // ``createSession`` already accepts a ``projectId``; passing it
      // here drops the new session straight into this project, removing
      // the redundant ``setSessionProject`` follow-up call.
      const session = await chatApi.createSession(persona.id, projectId)
      onClose()
      navigate(`/chat/${persona.id}/${session.id}`)
    } catch {
      addNotification({
        level: 'error',
        title: 'Could not start chat',
        message: 'Creating the new chat session failed.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function handleRemoveFromProject(persona: PersonaDto) {
    setBusy(true)
    try {
      await updatePersona(persona.id, { default_project_id: null })
    } catch {
      addNotification({
        level: 'error',
        title: 'Update failed',
        message: 'Could not remove the persona from this project.',
      })
    } finally {
      setBusy(false)
    }
  }

  async function commitSwitch(persona: PersonaDto) {
    setBusy(true)
    try {
      await updatePersona(persona.id, { default_project_id: projectId })
      setPickerOpen(false)
      setPickerQuery('')
      setPendingSwitch(null)
    } catch {
      addNotification({
        level: 'error',
        title: 'Update failed',
        message: 'Could not assign this persona to the project.',
      })
    } finally {
      setBusy(false)
    }
  }

  function handlePick(persona: PersonaDto) {
    if (persona.default_project_id && persona.default_project_id !== projectId) {
      const fromTitle =
        projects[persona.default_project_id]?.title ?? 'another project'
      setPendingSwitch({ persona, fromProjectTitle: fromTitle })
      return
    }
    void commitSwitch(persona)
  }

  return (
    <div
      className="flex-1 overflow-y-auto p-6"
      data-testid="project-personas-tab"
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {/* Header row */}
        <div className="flex items-center justify-between">
          <div className="flex flex-col">
            <span className="text-[14px] font-semibold text-white/85">
              Default personas in this project
            </span>
            <span className="text-[11px] text-white/50">
              Personas listed here open new chats inside this project by
              default.
            </span>
          </div>
          <div ref={pickerRef} className="relative">
            <button
              type="button"
              onClick={() => setPickerOpen((v) => !v)}
              data-testid="project-personas-add"
              className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] font-medium text-white/70 transition-colors hover:bg-white/6 hover:text-white/90"
            >
              + Add persona
            </button>
            {pickerOpen && (
              <div className="absolute right-0 top-full z-10 mt-1 w-80 rounded-md border border-white/10 bg-[#0f0d16] shadow-xl">
                <div className="border-b border-white/6 p-2">
                  <input
                    type="text"
                    value={pickerQuery}
                    onChange={(e) => setPickerQuery(e.target.value)}
                    placeholder="Search personas…"
                    aria-label="Search personas"
                    className="w-full rounded-md border border-white/10 bg-white/4 px-2 py-1 text-[12px] text-white/85 placeholder-white/35 outline-none focus:border-white/20"
                  />
                </div>
                <div className="max-h-72 overflow-y-auto">
                  {pickerCandidates.length === 0 ? (
                    <p className="px-3 py-2 text-[12px] text-white/45">
                      No personas available.
                    </p>
                  ) : (
                    pickerCandidates.map((persona) => (
                      <button
                        key={persona.id}
                        type="button"
                        onClick={() => handlePick(persona)}
                        data-testid={`project-personas-pick-${persona.id}`}
                        className="flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-white/6"
                      >
                        <PersonaAvatar persona={persona} />
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate text-[13px] text-white/85">
                            {persona.name}
                          </span>
                          {persona.tagline && (
                            <span className="truncate text-[11px] text-white/45">
                              {persona.tagline}
                            </span>
                          )}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <hr className="border-white/8" />

        {inProject.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-center">
            <p className="text-[13px] text-white/60">
              No default personas yet
            </p>
            <p className="max-w-xs text-[11px] leading-relaxed text-white/45">
              Use the picker above to assign one or more personas as
              defaults for new chats in this project.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {inProject.map((persona) => (
              <PersonaRow
                key={persona.id}
                persona={persona}
                disabled={busy}
                onStartChat={() => void handleStartChat(persona)}
                onRemove={() => void handleRemoveFromProject(persona)}
              />
            ))}
          </div>
        )}
      </div>

      {pendingSwitch && (
        <SwitchConfirmation
          personaName={pendingSwitch.persona.name}
          fromProjectTitle={pendingSwitch.fromProjectTitle}
          onCancel={() => setPendingSwitch(null)}
          onConfirm={() => void commitSwitch(pendingSwitch.persona)}
        />
      )}
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  disabled: boolean
  onStartChat: () => void
  onRemove: () => void
}

function PersonaRow({ persona, disabled, onStartChat, onRemove }: PersonaRowProps) {
  return (
    <div
      data-testid={`project-personas-row-${persona.id}`}
      className="flex items-start gap-3 rounded-md border border-white/8 bg-white/3 px-3 py-2.5"
    >
      <PersonaAvatar persona={persona} />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-[13px] font-semibold text-white/85">
          {persona.name}
        </span>
        {persona.tagline && (
          <span className="truncate text-[11px] text-white/55">
            {persona.tagline}
          </span>
        )}
        <div className="mt-1.5 flex items-center gap-2">
          <button
            type="button"
            onClick={onStartChat}
            disabled={disabled}
            data-testid={`project-personas-start-${persona.id}`}
            className="rounded border border-gold/35 bg-gold/12 px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors hover:bg-gold/18 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Start chat here
          </button>
          <button
            type="button"
            onClick={onRemove}
            disabled={disabled}
            data-testid={`project-personas-remove-${persona.id}`}
            className="rounded border border-white/10 px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-white/55 transition-colors hover:border-white/20 hover:text-white/80 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Remove from project
          </button>
        </div>
      </div>
    </div>
  )
}

function PersonaAvatar({ persona }: { persona: PersonaDto }) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme]
  return (
    <div
      className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
      style={{
        background: `${chakra.hex}33`,
        border: `1px solid ${chakra.hex}55`,
        color: chakra.hex,
      }}
    >
      {persona.monogram || persona.name.charAt(0).toUpperCase()}
    </div>
  )
}

interface SwitchConfirmationProps {
  personaName: string
  fromProjectTitle: string
  onCancel: () => void
  onConfirm: () => void
}

function SwitchConfirmation({
  personaName,
  fromProjectTitle,
  onCancel,
  onConfirm,
}: SwitchConfirmationProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Switch persona default project"
      data-testid="project-personas-switch-confirm"
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/60"
    >
      <div className="w-[min(420px,90vw)] rounded-lg border border-white/12 bg-elevated p-5 shadow-2xl">
        <h3 className="text-[14px] font-semibold text-white/90">
          Switch default project?
        </h3>
        <p className="mt-2 text-[12px] text-white/70">
          <span className="font-medium text-white/85">{personaName}</span> is
          currently default in{' '}
          <span className="font-medium text-white/85">"{fromProjectTitle}"</span>
          . Switch?
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            data-testid="project-personas-switch-cancel"
            className="rounded border border-white/10 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/65 transition-colors hover:border-white/20 hover:text-white/85"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            data-testid="project-personas-switch-confirm-go"
            className="rounded border border-gold/40 bg-gold/15 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors hover:bg-gold/22"
          >
            Switch
          </button>
        </div>
      </div>
    </div>
  )
}
