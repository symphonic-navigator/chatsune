import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'

interface OverviewTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function OverviewTab({ persona, chakra }: OverviewTabProps) {
  const createdDate = new Date(persona.created_at).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  return (
    <div className="flex flex-col items-center px-6 py-8 gap-6">
      {/* Avatar */}
      <div
        className="flex items-center justify-center rounded-full flex-shrink-0"
        style={{
          width: 120,
          height: 120,
          background: persona.profile_image ? undefined : `${chakra.hex}22`,
          border: `2px solid ${chakra.hex}55`,
          boxShadow: `0 0 28px ${chakra.glow}`,
        }}
      >
        {persona.profile_image ? (
          <img
            src={persona.profile_image}
            alt={persona.name}
            className="w-full h-full rounded-full object-cover"
          />
        ) : (
          <span
            className="text-4xl font-bold select-none"
            style={{ color: chakra.hex }}
          >
            {persona.monogram}
          </span>
        )}
      </div>

      {/* Name + tagline */}
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-[18px] font-semibold text-white/90">{persona.name}</h2>
        {persona.tagline && (
          <p className="text-[13px] text-white/45 max-w-xs">{persona.tagline}</p>
        )}
      </div>

      {/* Stats grid */}
      <div
        className="grid grid-cols-3 w-full max-w-sm rounded-xl overflow-hidden"
        style={{ border: `1px solid ${chakra.hex}22` }}
      >
        {[
          { label: 'Chats', value: '—' },
          { label: 'Memory tokens', value: '—' },
          { label: 'Pending journal', value: '—' },
        ].map((stat, i) => (
          <div
            key={stat.label}
            className="flex flex-col items-center gap-1 py-4 px-2"
            style={{
              background: `${chakra.hex}08`,
              borderRight: i < 2 ? `1px solid ${chakra.hex}22` : undefined,
            }}
          >
            <span className="text-[18px] font-semibold text-white/70">{stat.value}</span>
            <span className="text-[10px] text-white/35 text-center leading-tight">{stat.label}</span>
          </div>
        ))}
      </div>

      {/* Created date */}
      <p className="text-[11px] text-white/25 font-mono">
        created {createdDate}
      </p>
    </div>
  )
}
