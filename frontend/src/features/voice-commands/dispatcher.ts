import { normalise } from './normaliser'
import { match } from './matcher'
import { lookupCommand } from './registry'
import { respondToUser } from './responseChannel'
import type { CommandResponse, DispatchResult } from './types'

/**
 * Attempt to dispatch the STT-result text as a voice command.
 *
 * Returns `{dispatched:false}` when the text does not match any registered
 * trigger — caller should treat the text as a normal LLM prompt.
 *
 * On a match, runs the handler, renders the response, and returns the
 * `onTriggerWhilePlaying` flag so the caller can decide what to do with the
 * paused response Group. Handler throws are caught and converted to error
 * responses, with `onTriggerWhilePlaying` forced to 'resume' so a buggy
 * handler cannot kill the persona's reply.
 */
export async function tryDispatchCommand(text: string): Promise<DispatchResult> {
  const tokens = normalise(text)
  const hit = match(tokens)
  if (!hit) return { dispatched: false }

  const handler = lookupCommand(hit.trigger)!
  let response: CommandResponse
  try {
    response = await handler.execute(hit.body)
  } catch (err) {
    console.error(`[VoiceCommand] handler '${hit.trigger}' threw:`, err)
    response = {
      level: 'error',
      displayText: `Command '${hit.trigger}' failed — see console for details.`,
    }
    respondToUser(response)
    return { dispatched: true, onTriggerWhilePlaying: 'resume' }
  }

  respondToUser(response)
  return {
    dispatched: true,
    onTriggerWhilePlaying: response.onTriggerWhilePlaying ?? handler.onTriggerWhilePlaying,
  }
}
