import type { TagExecutionResult } from '../../types'
import * as api from './api'
import type { Action } from './api'

/** Actions the LLM can use in tags (lowercase for matching). */
const SIMPLE_ACTIONS = new Set<string>([
  'vibrate', 'rotate', 'pump', 'thrusting', 'fingering',
  'suction', 'depth', 'oscillate', 'all',
])

/**
 * Parse and execute a Lovense response tag.
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
 */
export async function executeTag(
  command: string,
  args: string[],
  config: Record<string, unknown>,
): Promise<TagExecutionResult> {
  const ip = config.ip as string | undefined
  if (!ip) {
    return { success: false, displayText: '_[Lovense: no IP configured]_' }
  }

  const cmd = command.toLowerCase()

  try {
    // <lovense stopall>
    if (cmd === 'stopall' && args.length === 0) {
      await api.stopAll(ip)
      return { success: true, displayText: '_stop all toys_' }
    }

    // All other commands need at least a toy name
    // The "command" from the tag parser is the first word after "lovense",
    // which is the toy name. The action is in args[0].
    const toyName = command
    const action = (args[0] ?? '').toLowerCase()

    // <lovense TOYNAME stop>
    if (action === 'stop') {
      await api.stopToy(ip, toyName)
      return { success: true, displayText: `_stop ${toyName}_` }
    }

    // <lovense TOYNAME stroke STROKE_POS THRUST_STRENGTH [SECONDS]>
    if (action === 'stroke') {
      const strokePos = parseInt(args[1], 10) || 50
      const thrustStrength = parseInt(args[2], 10) || 10
      const seconds = parseInt(args[3], 10) || 0
      const result = await api.strokeCommand(ip, strokePos, thrustStrength, seconds, toyName)
      if (result.code === 400) {
        return { success: false, displayText: `_[Lovense: ${result.message}]_` }
      }
      const timeText = seconds > 0 ? ` for ${seconds}s` : ''
      return {
        success: true,
        displayText: `_stroke ${toyName} at ${strokePos}/${thrustStrength}${timeText}_`,
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

      await api.functionCommand(ip, {
        action: cappedAction,
        strength,
        timeSec: seconds,
        toy: toyName,
        loopRunningSec: loopRun,
        loopPauseSec: loopPause,
        stopPrevious: layer ? false : undefined,
      })

      // Build display text
      const parts: string[] = [`_${action} ${toyName} at ${strength}`]
      if (seconds > 0) parts.push(`for ${seconds}s`)
      if (loopRun && loopPause) parts.push(`(${loopRun}s on, ${loopPause}s pause)`)
      if (layer) parts.push('[layered]')

      return { success: true, displayText: parts.join(' ') + '_' }
    }

    return { success: false, displayText: `_[Lovense: unknown action "${action}"]_` }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { success: false, displayText: `_[Lovense error: ${msg}]_` }
  }
}
