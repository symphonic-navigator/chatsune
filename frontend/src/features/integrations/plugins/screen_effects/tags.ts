import type { TagExecutionResult } from '../../types'
import { risingEmojis } from './effects/risingEmojis'

type EffectFn = (args: string[]) => TagExecutionResult

const EFFECTS: Record<string, EffectFn> = {
  rising_emojis: risingEmojis,
}

/**
 * Dispatch a screen_effect tag to its effect builder.
 *
 * Synchronous, deterministic over (command, args). Unknown commands return
 * an "unknown" pill — the buffer's error pill is reserved for thrown
 * exceptions, which we deliberately avoid.
 */
export function executeTag(
  command: string,
  args: string[],
  _config: Record<string, unknown>,
): TagExecutionResult {
  const fn = EFFECTS[command.toLowerCase()]
  if (!fn) {
    return {
      pillContent: `screen_effect: unknown "${command}"`,
      syncWithTts: true,
      effectPayload: { error: 'unknown_effect', command },
    }
  }
  return fn(args)
}
