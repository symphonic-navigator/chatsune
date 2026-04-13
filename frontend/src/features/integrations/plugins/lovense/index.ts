import type { IntegrationPlugin } from '../../types'
import { registerPlugin } from '../../registry'
import { executeTag } from './tags'
import * as api from './api'
import { LovenseConfig } from './config'

const lovensePlugin: IntegrationPlugin = {
  id: 'lovense',

  executeTag,

  executeTool: async (toolName, _args, config) => {
    const ip = config.ip as string | undefined
    if (!ip) return JSON.stringify({ error: 'No IP configured' })

    if (toolName === 'lovense_get_toys') {
      try {
        const result = await api.getToys(ip)
        return JSON.stringify(result)
      } catch (err) {
        return JSON.stringify({ error: err instanceof Error ? err.message : String(err) })
      }
    }

    return JSON.stringify({ error: `Unknown tool: ${toolName}` })
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
