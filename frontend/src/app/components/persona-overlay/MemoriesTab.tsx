import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'

interface MemoriesTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function MemoriesTab({ persona: _persona, chakra: _chakra }: MemoriesTabProps) {
  return (
    <div className="flex flex-1 items-center justify-center h-full py-20">
      <p className="font-mono text-[12px] text-white/20 text-center">
        memory entries — coming with the memory module
      </p>
    </div>
  )
}
