import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { sortPersonas } from './personaSort'

interface NewChatRowProps {
  personas: PersonaDto[]
  onCloseModal: () => void
}

export function NewChatRow({ personas, onCloseModal }: NewChatRowProps) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
    return sortPersonas(filtered)
  }, [personas, isSanitised])

  function startNewChat(persona: PersonaDto) {
    onCloseModal()
    setOpen(false)
    navigate(`/chat/${persona.id}?new=1`)
  }

  return (
    <div className="flex-shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/5"
      >
        <span className="text-[14px]">🪶</span>
        <span className="flex-1 text-[12px] font-medium uppercase tracking-wider text-white/70 group-hover:text-white/90">
          New Chat
        </span>
        <span className="text-[10px] text-white/40">{open ? '∨' : '›'}</span>
      </button>

      {open && (
        <div className="mx-2 mt-0.5 mb-1 rounded-md border border-white/6 bg-white/2 py-1">
          {visible.length === 0 ? (
            <p className="px-3 py-1 text-[11px] text-white/40">No personas available</p>
          ) : (
            visible.map((persona) => (
              <button
                key={persona.id}
                type="button"
                data-testid="new-chat-persona"
                onClick={() => startNewChat(persona)}
                className="flex w-full items-center gap-2 px-3 py-1 text-left text-[12px] text-white/80 transition-colors hover:bg-white/6"
              >
                {persona.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
