import type { TagExecutionResult } from '../../../types'

const MAX_EMOJIS = 5
const FALLBACK_EMOJI = '✨'

/**
 * Build a TagExecutionResult for the rising_emojis effect.
 *
 * Pure / deterministic over (args). No randomness — the visible randomness
 * (per-particle size, drift, rotation) lives in RisingEmojisEffect at spawn
 * time so live-stream and persisted re-renders produce identical pills.
 */
export function risingEmojis(args: string[]): TagExecutionResult {
  const emojis = parseEmojis(args)
  if (emojis.length === 0) {
    return {
      pillContent: '✨ rising_emojis (no emojis)',
      syncWithTts: true,
      effectPayload: { effect: 'rising_emojis', emojis: [FALLBACK_EMOJI] },
    }
  }
  return {
    pillContent: `✨ rising_emojis ${emojis.join('')}`,
    syncWithTts: true,
    effectPayload: { effect: 'rising_emojis', emojis },
  }
}

/**
 * Split args into a deduped list of grapheme-correct emoji clusters.
 *
 * Accepts both space-separated args (`['💖', '🤘', '🔥']`) and a single
 * concatenated string (`['💖🤘🔥']`); ZWJ sequences and skin-tone modifiers
 * are preserved as a single grapheme. Whitespace-only segments are dropped.
 * Hard-capped at MAX_EMOJIS to bound the visual cost.
 */
export function parseEmojis(args: string[]): string[] {
  const seg = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  const out: string[] = []
  const seen = new Set<string>()
  for (const arg of args) {
    for (const { segment } of seg.segment(arg)) {
      const trimmed = segment.trim()
      if (!trimmed) continue
      if (seen.has(trimmed)) continue
      seen.add(trimmed)
      out.push(trimmed)
      if (out.length >= MAX_EMOJIS) return out
    }
  }
  return out
}
