import type { TagExecutionResult } from '../../types'
import * as api from './api'

export async function executeTag(
  command: string,
  args: string[],
  config: Record<string, unknown>,
): Promise<TagExecutionResult> {
  const ip = config.ip as string | undefined
  if (!ip) {
    return { success: false, displayText: '_[Lovense: no IP configured]_' }
  }

  try {
    switch (command.toLowerCase()) {
      case 'vibrate': {
        const [toy, strengthStr, secondsStr] = args
        const strength = parseInt(strengthStr, 10) || 5
        const seconds = parseInt(secondsStr, 10) || 0
        await api.vibrate(ip, toy, strength, seconds)
        return {
          success: true,
          displayText: seconds > 0
            ? `_vibrate ${toy} at strength ${strength} for ${seconds}s_`
            : `_vibrate ${toy} at strength ${strength}_`,
        }
      }
      case 'rotate': {
        const [toy, strengthStr, secondsStr] = args
        const strength = parseInt(strengthStr, 10) || 5
        const seconds = parseInt(secondsStr, 10) || 0
        await api.rotate(ip, toy, strength, seconds)
        return {
          success: true,
          displayText: seconds > 0
            ? `_rotate ${toy} at strength ${strength} for ${seconds}s_`
            : `_rotate ${toy} at strength ${strength}_`,
        }
      }
      case 'stop': {
        const [toy] = args
        await api.stopToy(ip, toy)
        return { success: true, displayText: `_stop ${toy}_` }
      }
      case 'stopall': {
        await api.stopAll(ip)
        return { success: true, displayText: '_stop all toys_' }
      }
      default:
        return { success: false, displayText: `_[Lovense: unknown command "${command}"]_` }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { success: false, displayText: `_[Lovense error: ${msg}]_` }
  }
}
