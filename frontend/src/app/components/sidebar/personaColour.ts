import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra";

export function personaGradient(persona: { colour_scheme: string }): string {
  const entry = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour];
  if (entry) {
    return `linear-gradient(135deg, ${entry.hex}50, ${entry.hex}10)`;
  }
  return `linear-gradient(135deg, #C9A84C50, #C9A84C10)`;
}

export function personaHex(persona: { colour_scheme: string }): string {
  const entry = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour];
  return entry?.hex ?? "#C9A84C";
}

export function personaInitial(persona: { name: string }): string {
  return persona.name.charAt(0).toUpperCase();
}
