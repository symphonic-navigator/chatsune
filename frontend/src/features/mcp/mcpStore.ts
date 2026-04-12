import { create } from 'zustand'
import type { McpGatewayConfig, McpSessionGateway } from './types'

const LOCAL_STORAGE_KEY = 'chatsune:mcp_local_gateways'

interface McpState {
  /** User's local gateways (localStorage, this device only) */
  localGateways: McpGatewayConfig[]
  /** All discovered MCP gateways for current session (set after discovery) */
  sessionGateways: McpSessionGateway[]

  loadLocalGateways: () => void
  addLocalGateway: (gw: McpGatewayConfig) => void
  updateLocalGateway: (id: string, updates: Partial<McpGatewayConfig>) => void
  deleteLocalGateway: (id: string) => void
  setSessionGateways: (gateways: McpSessionGateway[]) => void
  clearSessionGateways: () => void
}

function migrateGateway(gw: McpGatewayConfig): McpGatewayConfig {
  return {
    ...gw,
    server_configs: gw.server_configs ?? {},
    tool_overrides: gw.tool_overrides ?? [],
  }
}

function readLocalGateways(): McpGatewayConfig[] {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as McpGatewayConfig[]) : []
  } catch {
    return []
  }
}

function writeLocalGateways(gateways: McpGatewayConfig[]): void {
  localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(gateways))
}

export const useMcpStore = create<McpState>((set, get) => ({
  localGateways: [],
  sessionGateways: [],

  loadLocalGateways: () => {
    set({ localGateways: readLocalGateways().map(migrateGateway) })
  },

  addLocalGateway: (gw) => {
    const updated = [...get().localGateways, gw]
    writeLocalGateways(updated)
    set({ localGateways: updated })
  },

  updateLocalGateway: (id, updates) => {
    const updated = get().localGateways.map((gw) =>
      gw.id === id ? { ...gw, ...updates } : gw,
    )
    writeLocalGateways(updated)
    set({ localGateways: updated })
  },

  deleteLocalGateway: (id) => {
    const updated = get().localGateways.filter((gw) => gw.id !== id)
    writeLocalGateways(updated)
    set({ localGateways: updated })
  },

  setSessionGateways: (gateways) => set({ sessionGateways: gateways }),
  clearSessionGateways: () => set({ sessionGateways: [] }),
}))
