import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'

interface MobileNewChatViewProps {
  personas: PersonaDto[]
  onSelect: (persona: PersonaDto) => void
  /** Called when the empty-state "Create persona" link is tapped. Gives the
   *  sidebar a chance to close the drawer before route navigation. */
  onClose?: () => void
}

export function MobileNewChatView({ personas, onSelect, onClose }: MobileNewChatViewProps) {
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    return isSanitised ? personas.filter((p) => !p.nsfw) : personas
  }, [personas, isSanitised])

  const pinned = visible.filter((p) => p.pinned)
  const other = visible.filter((p) => !p.pinned)

  if (visible.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
        <p className="mb-3 text-[14px] text-white/60">No personas yet</p>
        <Link
          to="/personas"
          replace
          onClick={onClose}
          className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[12px] text-white/80 transition-colors hover:bg-white/10"
        >
          Create persona
        </Link>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto py-1 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
      {pinned.length > 0 && (
        <>
          <div className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/45">
            Pinned
          </div>
          {pinned.map((p) => (
            <PersonaRow key={p.id} persona={p} onSelect={onSelect} />
          ))}
        </>
      )}

      {other.length > 0 && (
        <>
          <div className="px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/45">
            Other
          </div>
          {other.map((p) => (
            <PersonaRow key={p.id} persona={p} onSelect={onSelect} />
          ))}
        </>
      )}
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  onSelect: (persona: PersonaDto) => void
}

function PersonaRow({ persona, onSelect }: PersonaRowProps) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme] ?? CHAKRA_PALETTE.solar
  const monogram = persona.monogram || persona.name.charAt(0).toUpperCase()
  return (
    <button
      type="button"
      onClick={() => onSelect(persona)}
      className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-white/4"
    >
      <span
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-[14px] font-semibold"
        style={{
          background: `${chakra.hex}22`,
          border: `1px solid ${chakra.hex}55`,
          color: chakra.hex,
        }}
      >
        {monogram}
      </span>
      <span className="flex-1 truncate text-[14px] text-white/85">{persona.name}</span>
      {persona.nsfw && (
        <span className="flex-shrink-0 rounded-full border border-pink-400/35 bg-pink-400/15 px-1.5 py-[1px] text-[9px] font-semibold uppercase tracking-wider text-pink-200/90">
          NSFW
        </span>
      )}
    </button>
  )
}
