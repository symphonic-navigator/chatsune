import type { IntegrationPlugin } from '../../types'
import { registerPlugin } from '../../registry'
import { executeTag } from './tags'
import * as api from './api'
import { LovenseConfig } from './config'

const lovensePlugin: IntegrationPlugin = {
  id: 'lovense',

  executeTag,

  executeTool: async (toolName, args, config) => {
    const ip = config.ip as string | undefined
    if (!ip) return JSON.stringify({ error: 'No IP configured' })

    try {
      if (toolName === 'lovense_get_toys') {
        const raw = await api.getToys(ip)
        const parsed = api.parseGetToysResponse(raw)
        if (!parsed.ok) {
          return JSON.stringify({ error: 'Failed to query toys', raw })
        }
        const toys = parsed.toys.map((t) => ({
          name: t.name,
          nickName: t.nickName || undefined,
          status: t.status,
          battery: t.battery,
          capabilities: t.capabilities,
        }))
        return JSON.stringify({
          connected_toys: toys,
          count: toys.length,
          platform: parsed.platform,
        })
      }

      if (toolName === 'lovense_control') {
        const action = (args.action as string) ?? ''
        const toy = (args.toy as string) ?? ''
        const strength = (args.strength as number) ?? 0
        const timeSec = (args.time_sec as number) ?? 0
        const loopRun = args.loop_running_sec as number | undefined
        const loopPause = args.loop_pause_sec as number | undefined
        const layer = (args.layer as boolean) ?? false

        // Handle stroke separately
        if (action.toLowerCase() === 'stroke') {
          const strokePosition = (args.stroke_position as number) ?? 50
          const result = await api.strokeCommand(ip, strokePosition, strength, timeSec, toy)
          return JSON.stringify(result)
        }

        // Handle stop
        if (action.toLowerCase() === 'stop') {
          const result = toy
            ? await api.stopToy(ip, toy)
            : await api.stopAll(ip)
          return JSON.stringify(result)
        }

        // Regular function command
        const cappedAction = (action.charAt(0).toUpperCase() + action.slice(1)) as api.Action
        const result = await api.functionCommand(ip, {
          action: cappedAction,
          strength,
          timeSec,
          toy: toy || undefined,
          loopRunningSec: loopRun,
          loopPauseSec: loopPause,
          stopPrevious: layer ? false : undefined,
        })
        return JSON.stringify(result)
      }

      return JSON.stringify({ error: `Unknown tool: ${toolName}` })
    } catch (err) {
      return JSON.stringify({ error: err instanceof Error ? err.message : String(err) })
    }
  },

  healthCheck: async (config) => {
    const ip = config.ip as string | undefined
    if (!ip) return 'unknown'
    try {
      const result = await api.getToys(ip)
      if (typeof result === 'object' && result !== null) {
        const data = result.data as Record<string, unknown> | undefined
        if (data && Object.keys(data).length > 0) return 'connected'
        return 'reachable'
      }
      return 'reachable'
    } catch {
      return 'unreachable'
    }
  },

  emergencyStop: async (config) => {
    const ip = config.ip as string | undefined
    if (ip) {
      await api.stopAll(ip)
    }
  },

  ConfigComponent: LovenseConfig,
}

registerPlugin(lovensePlugin)

export default lovensePlugin
