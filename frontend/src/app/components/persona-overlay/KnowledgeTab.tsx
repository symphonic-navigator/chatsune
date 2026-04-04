import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'

interface KnowledgeTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function KnowledgeTab({ persona: _persona, chakra: _chakra }: KnowledgeTabProps) {
  return (
    <div className="flex flex-1 items-center justify-center h-full py-20">
      <p className="font-mono text-[12px] text-white/20 text-center">
        knowledge libraries — coming with the knowledge module
      </p>
    </div>
  )
}
