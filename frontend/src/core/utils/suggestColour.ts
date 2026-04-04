import type { ChakraColour } from "../types/chakra";

const ALL_COLOURS: ChakraColour[] = [
  "root", "sacral", "solar", "heart", "throat", "third_eye", "crown",
];

/**
 * Pick a random colour from those with the lowest usage count.
 * If no personas exist, picks from all colours equally.
 */
export function suggestColour(existingSchemes: ChakraColour[]): ChakraColour {
  const counts = new Map<ChakraColour, number>(
    ALL_COLOURS.map((c) => [c, 0]),
  );
  for (const scheme of existingSchemes) {
    counts.set(scheme, (counts.get(scheme) ?? 0) + 1);
  }
  const minCount = Math.min(...counts.values());
  const leastUsed = ALL_COLOURS.filter((c) => counts.get(c) === minCount);
  return leastUsed[Math.floor(Math.random() * leastUsed.length)];
}
