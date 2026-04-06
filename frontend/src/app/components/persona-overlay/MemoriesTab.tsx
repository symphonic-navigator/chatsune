import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'

interface MemoriesTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function MemoriesTab({ persona: _persona, chakra }: MemoriesTabProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center h-full py-20 gap-3">
      <div
        className="flex h-10 w-10 items-center justify-center rounded-full text-lg"
        style={{ background: `${chakra.hex}15`, color: `${chakra.hex}80` }}
      >
        &#x2726;
      </div>
      <p className="text-[13px] text-white/30 text-center">
        This feature is coming soon.
      </p>
    </div>
  )
}
