import type { PersonaDto } from "../../../core/types/persona"

const PALETTE: [string, string][] = [
  ["#7c5cbf", "#c9a84c"],
  ["#1e6fbf", "#34d399"],
  ["#bf4f1e", "#f59e0b"],
  ["#2e7d32", "#66bb6a"],
  ["#7b1fa2", "#e91e63"],
  ["#0277bd", "#80deea"],
]

function hashId(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) {
    h = (Math.imul(31, h) + id.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

export function personaGradient(persona: PersonaDto): string {
  if (/^#[0-9a-fA-F]{3,8}$/.test(persona.colour_scheme ?? "")) {
    return `linear-gradient(135deg, ${persona.colour_scheme}, ${persona.colour_scheme}88)`
  }
  const [from, to] = PALETTE[hashId(persona.id) % PALETTE.length]
  return `linear-gradient(135deg, ${from}, ${to})`
}

export function personaInitial(persona: PersonaDto): string {
  return persona.name.charAt(0).toUpperCase()
}
