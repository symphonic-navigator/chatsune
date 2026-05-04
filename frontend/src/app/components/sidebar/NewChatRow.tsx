import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import { sortPersonas } from './personaSort'
import { FeatherIcon, KissMarkIcon, SunglassesIcon } from '../../../core/components/symbols'

interface NewChatRowProps {
  personas: PersonaDto[]
  onCloseModal: () => void
  mode?: 'normal' | 'incognito'
}

export function NewChatRow({ personas, onCloseModal, mode = 'normal' }: NewChatRowProps) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
    return sortPersonas(filtered)
  }, [personas, isSanitised])

  const isIncognito = mode === 'incognito'
  const Icon = isIncognito ? SunglassesIcon : FeatherIcon
  const label = isIncognito ? 'New Incognito Chat' : 'New Chat'
  const urlSuffix = isIncognito ? '?incognito=1' : '?new=1'

  function startNewChat(persona: PersonaDto) {
    onCloseModal()
    setOpen(false)
    navigate(`/chat/${persona.id}${urlSuffix}`)
  }

  return (
    <div className="flex-shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/5"
      >
        <Icon style={{ fontSize: '14px' }} />
        <span className="flex-1 text-[12px] font-medium uppercase tracking-wider text-white/70 group-hover:text-white/90">
          {label}
        </span>
        <span className="text-[10px] text-white/40">{open ? '∨' : '›'}</span>
      </button>

      {open && (
        <div className="mx-2 mt-0.5 mb-1 rounded-md border border-white/6 bg-white/2 py-1">
          {visible.length === 0 ? (
            <p className="px-3 py-1 text-[11px] text-white/40">No personas available</p>
          ) : (
            visible.map((persona) => {
              const chakra = CHAKRA_PALETTE[persona.colour_scheme]
              const monogram = persona.monogram || persona.name.charAt(0).toUpperCase()
              return (
                <button
                  key={persona.id}
                  type="button"
                  data-testid="new-chat-persona"
                  onClick={() => startNewChat(persona)}
                  className="flex w-full items-center gap-2 px-3 py-1 text-left text-[12px] text-white/80 transition-colors hover:bg-white/6"
                >
                  <span
                    className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
                    style={{
                      background: `${chakra.hex}22`,
                      border: `1px solid ${chakra.hex}55`,
                      color: chakra.hex,
                    }}
                  >
                    {monogram}
                  </span>
                  <span className="flex-1 truncate">{persona.name}</span>
                  {persona.nsfw && (
                    <span aria-label="NSFW" title="NSFW">
                      <KissMarkIcon style={{ fontSize: '12px' }} />
                    </span>
                  )}
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
