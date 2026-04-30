import type { TagExecutionResult } from '../../types'
import * as api from './api'
import type { Action } from './api'

/** Actions the LLM can use in tags (lowercase for matching). */
const SIMPLE_ACTIONS = new Set<string>([
  'vibrate', 'rotate', 'pump', 'thrusting', 'fingering',
  'suction', 'depth', 'oscillate', 'all',
])

/**
 * Parse a Lovense response tag synchronously.
 *
 * Returns a `TagExecutionResult` describing the inline pill, the trigger-
 * event payload, and an optional fire-and-forget `sideEffect` thunk that
 * carries the actual hardware call. The buffer (responseTagProcessor) drives
 * pill rendering and trigger emission from the synchronous fields alone.
 *
 * Tag format:
 *   <lovense TOYNAME ACTION STRENGTH [SECONDS] [loop RUN PAUSE] [layer]>
 *   <lovense TOYNAME stroke STROKE_POS THRUST_STRENGTH [SECONDS]>
 *   <lovense TOYNAME stop>
 *   <lovense stopall>
 *
 * Examples:
 *   <lovense nova vibrate 10 5>
 *   <lovense nova vibrate 10 30 loop 3 2>
 *   <lovense nova rotate 8 5 layer>
 *   <lovense nova stroke 50 10 5>
 *   <lovense nova stop>
 *   <lovense stopall>
 *
 * Hardware actions are always `syncWithTts: false` so they fire when the tag
 * is parsed rather than when the surrounding sentence reaches TTS — this
 * keeps the response feeling immediate.
 */
export function executeTag(
  command: string,
  args: string[],
  config: Record<string, unknown>,
): TagExecutionResult {
  const ip = config.ip as string | undefined
  if (!ip) {
    return {
      pillContent: 'Lovense: no IP configured',
      syncWithTts: false,
      effectPayload: { error: 'no_ip' },
    }
  }

  const cmd = command.toLowerCase()

  // <lovense stopall>
  if (cmd === 'stopall' && args.length === 0) {
    return {
      pillContent: 'stop all toys',
      syncWithTts: false,
      effectPayload: { kind: 'stopall' },
      sideEffect: () => api.stopAll(ip).then(() => undefined),
    }
  }

  // All other commands need at least a toy name.
  // The "command" from the tag parser is the first word after "lovense",
  // which is the toy name. The action is in args[0].
  const toyName = command
  const action = (args[0] ?? '').toLowerCase()

  // <lovense TOYNAME stop>
  if (action === 'stop') {
    return {
      pillContent: `stop ${toyName}`,
      syncWithTts: false,
      effectPayload: { kind: 'stop', toy: toyName },
      sideEffect: () => api.stopToy(ip, toyName).then(() => undefined),
    }
  }

  // <lovense TOYNAME stroke STROKE_POS THRUST_STRENGTH [SECONDS]>
  if (action === 'stroke') {
    const strokePos = parseInt(args[1], 10) || 50
    const thrustStrength = parseInt(args[2], 10) || 10
    const seconds = parseInt(args[3], 10) || 0
    const timeText = seconds > 0 ? ` for ${seconds}s` : ''
    return {
      pillContent: `stroke ${toyName} at ${strokePos}/${thrustStrength}${timeText}`,
      syncWithTts: false,
      effectPayload: { kind: 'stroke', toy: toyName, strokePos, thrustStrength, seconds },
      sideEffect: async () => {
        const r = await api.strokeCommand(ip, strokePos, thrustStrength, seconds, toyName)
        if (r.code === 400) throw new Error(String(r.message ?? 'stroke command rejected'))
      },
    }
  }

  // <lovense TOYNAME ACTION STRENGTH [SECONDS] [loop RUN PAUSE] [layer]>
  if (SIMPLE_ACTIONS.has(action)) {
    const strength = parseInt(args[1], 10) || 5
    const cappedAction = (action.charAt(0).toUpperCase() + action.slice(1)) as Action

    // Parse remaining args for seconds, loop, layer
    let seconds = 0
    let loopRun: number | undefined
    let loopPause: number | undefined
    let layer = false
    let i = 2

    // Next arg could be seconds (number), 'loop', or 'layer'
    if (args[i] && !isNaN(parseInt(args[i], 10)) && args[i] !== 'loop' && args[i] !== 'layer') {
      seconds = parseInt(args[i], 10) || 0
      i++
    }

    // Check for 'loop RUN PAUSE'
    if (args[i]?.toLowerCase() === 'loop') {
      loopRun = parseInt(args[i + 1], 10) || undefined
      loopPause = parseInt(args[i + 2], 10) || undefined
      i += 3
    }

    // Check for 'layer'
    if (args[i]?.toLowerCase() === 'layer' || args[i - 1]?.toLowerCase() === 'layer') {
      layer = true
    }

    // Build pill text by joining parts with spaces (no leading/trailing
    // underscores — pill rendering is handled by the rehype plugin now).
    const parts: string[] = [`${action} ${toyName} at ${strength}`]
    if (seconds > 0) parts.push(`for ${seconds}s`)
    if (loopRun && loopPause) parts.push(`(${loopRun}s on, ${loopPause}s pause)`)
    if (layer) parts.push('[layered]')

    return {
      pillContent: parts.join(' '),
      syncWithTts: false,
      effectPayload: {
        kind: 'simple',
        toy: toyName,
        action: cappedAction,
        strength,
        seconds,
        loopRun,
        loopPause,
        layer,
      },
      sideEffect: () =>
        api
          .functionCommand(ip, {
            action: cappedAction,
            strength,
            timeSec: seconds,
            toy: toyName,
            loopRunningSec: loopRun,
            loopPauseSec: loopPause,
            stopPrevious: layer ? false : undefined,
          })
          .then(() => undefined),
    }
  }

  return {
    pillContent: `Lovense: unknown action "${action}"`,
    syncWithTts: false,
    effectPayload: { error: 'unknown_action', action },
  }
}
