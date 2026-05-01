import { normalise } from './normaliser'
import { match } from './matcher'
import { lookupCommand } from './registry'
import { respondToUser } from './responseChannel'
import { isKnownVoiceSub } from './handlers/voice'
import type { CommandResponse, DispatchResult } from './types'

/**
 * Attempt to dispatch the STT-result text as a voice command.
 *
 * Returns `{dispatched:false}` when the text does not match any registered
 * trigger — caller should treat the text as a normal LLM prompt.
 *
 * On a match, runs the handler, renders the response, and returns the
 * `onTriggerWhilePlaying` flag so the caller can decide what to do with the
 * paused response Group. The returned `onTriggerWhilePlaying` is the
 * response's per-call override (`CommandResponse.onTriggerWhilePlaying`)
 * when set, otherwise the spec's static default
 * (`CommandSpec.onTriggerWhilePlaying`) — handlers can therefore branch
 * dynamically per call. Handler throws are caught and converted to error
 * responses, with `onTriggerWhilePlaying` forced to 'resume' so a buggy
 * handler cannot kill the persona's reply.
 */
export async function tryDispatchCommand(text: string): Promise<DispatchResult> {
  const tokens = normalise(text)
  // Diagnostic — covers both STT-upstream (active mode) and Vosk (paused mode)
  // entry points. Lets a misheard 'voice off' (turning into e.g. 'force off')
  // be diagnosed against the raw text without re-running the session.
  console.info('[VoiceCommand] dispatch entry: text=%o tokens=%o', text, tokens)

  // Voice-specific pre-check: first token "voice" with a missing or unknown sub.
  // 2-token form is almost certainly a misheard command — suppress LLM dispatch.
  // 1 or 3+ tokens is much more likely a normal sentence — fall through to LLM.
  // Known sub at any length proceeds to the matcher and handler.
  if (tokens[0] === 'voice' && (tokens.length < 2 || !isKnownVoiceSub(tokens[1]))) {
    if (tokens.length === 2) {
      console.warn('[VoiceCommand] Rejected 2-token "voice <unknown>":', tokens)
      // TODO: add error toast and audible feedback with error sound
      return { dispatched: true, onTriggerWhilePlaying: 'resume' }
    }
    return { dispatched: false }
  }

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
