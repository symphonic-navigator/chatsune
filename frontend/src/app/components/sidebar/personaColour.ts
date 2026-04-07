import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra";

const HEX_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

export function personaGradient(persona: { colour_scheme: string }): string {
  const entry = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour];
  if (entry) {
    return `linear-gradient(135deg, ${entry.hex}50, ${entry.hex}10)`;
  }
  if (HEX_RE.test(persona.colour_scheme)) {
    return `linear-gradient(135deg, ${persona.colour_scheme}50, ${persona.colour_scheme}10)`;
  }
  return `linear-gradient(135deg, #C9A84C50, #C9A84C10)`;
}

export function personaHex(persona: { colour_scheme: string }): string {
  const entry = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour];
  if (entry) return entry.hex;
  if (HEX_RE.test(persona.colour_scheme)) return persona.colour_scheme;
  return "#C9A84C";
}

export function personaInitial(persona: { name: string }): string {
  return persona.name.charAt(0).toUpperCase();
}
