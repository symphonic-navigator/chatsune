import { hasCommand } from './registry'

export interface MatchResult {
  trigger: string
  body: string
}

/**
 * Return the trigger + body if `tokens[0]` is a registered command, else null.
 *
 * Tokens are assumed to be the output of `normalise()` — already lowercased,
 * punctuation-free, with leading fillers stripped. Word-boundary discipline
 * is enforced for free by tokenisation: 'companionship' is a single token
 * and never matches 'companion'.
 */
export function match(tokens: string[]): MatchResult | null {
  if (tokens.length === 0) return null
  const trigger = tokens[0]
  if (!hasCommand(trigger)) return null
  return { trigger, body: tokens.slice(1).join(' ') }
}
