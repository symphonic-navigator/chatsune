import { useMemo } from 'react'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
import type { PersonaDto } from '../../../core/types/persona'
import { sortPersonas } from '../sidebar/personaSort'
import { PINNED_STRIPE_STYLE } from '../sidebar/pinnedStripe'

interface PersonasTabProps {
  onOpenPersonaOverlay: (personaId: string) => void
  onCreatePersona: () => void
}

export function PersonasTab({ onOpenPersonaOverlay, onCreatePersona }: PersonasTabProps) {
  const { personas, update } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
    return sortPersonas(filtered)
  }, [personas, isSanitised])

  return (
    <div className="flex h-full flex-col">
      {/* Top bar with create button */}
      <div className="flex flex-shrink-0 items-center justify-end px-4 pt-4 pb-2">
        <button
          type="button"
          onClick={onCreatePersona}
          className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] font-medium text-white/70 transition-colors hover:bg-white/6 hover:text-white/90"
          aria-label="Create persona"
          title="Create persona"
        >
          + Create persona
        </button>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto px-4 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        <div className="flex flex-col gap-2">
          {visible.map((persona) => (
            <PersonaRow
              key={persona.id}
              persona={persona}
              onOpen={() => onOpenPersonaOverlay(persona.id)}
              onTogglePin={() => update(persona.id, { pinned: !persona.pinned })}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  onOpen: () => void
  onTogglePin: () => void
}

function PersonaRow({ persona, onOpen, onTogglePin }: PersonaRowProps) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme]
  const modelLabel = persona.model_unique_id ? persona.model_unique_id.split(':').slice(1).join(':') : 'no model'

  const baseStyle: React.CSSProperties = {
    border: `1px solid ${chakra.hex}22`,
  }
  const style: React.CSSProperties = persona.pinned
    ? { ...baseStyle, ...PINNED_STRIPE_STYLE }
    : baseStyle

  return (
    <div
      data-testid="persona-row"
      data-persona-id={persona.id}
      className="relative flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
      style={style}
    >
      <div
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full"
        style={{ background: `${chakra.hex}22`, border: `1px solid ${chakra.hex}55` }}
      >
        {persona.profile_image ? (
          <CroppedAvatar
            personaId={persona.id}
            updatedAt={persona.updated_at}
            crop={persona.profile_crop}
            size={28}
            alt={persona.name}
          />
        ) : (
          <span className="text-[11px] font-semibold" style={{ color: chakra.hex }}>
            {persona.monogram}
          </span>
        )}
      </div>

      <button
        type="button"
        data-testid="persona-row-body"
        onClick={onOpen}
        className="flex min-w-0 flex-1 flex-col items-start bg-transparent border-none p-0 text-left cursor-pointer"
      >
        <span className="truncate text-[13px] font-medium text-white/90">{persona.name}</span>
        {persona.tagline && (
          <span className="truncate text-[11px] text-white/45">{persona.tagline}</span>
        )}
        <span
          className="truncate font-mono text-[10px]"
          style={{ color: chakra.hex + '4d', letterSpacing: '0.5px' }}
        >
          {modelLabel}
        </span>
      </button>

      {persona.nsfw && (
        <span
          data-testid="persona-nsfw-indicator"
          className="absolute top-1 right-1 text-[10px] leading-none"
          aria-label="NSFW"
          title="NSFW"
        >
          💋
        </span>
      )}

      <button
        type="button"
        data-testid="persona-pin-toggle"
        onClick={(e) => {
          e.stopPropagation()
          onTogglePin()
        }}
        className="rounded p-1 transition-colors"
        style={{
          color: persona.pinned ? chakra.hex : 'rgba(255,255,255,0.2)',
          background: persona.pinned ? chakra.hex + '1a' : 'transparent',
        }}
        aria-label={persona.pinned ? 'Unpin' : 'Pin'}
        title={persona.pinned ? 'Unpin' : 'Pin'}
      >
        📌
      </button>
    </div>
  )
}
