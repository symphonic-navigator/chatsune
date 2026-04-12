import { create } from 'zustand'
import type { McpGatewayConfig, McpToolDefinition } from './types'

const LOCAL_STORAGE_KEY = 'chatsune:mcp_local_gateways'

interface SessionToolEntry {
  namespace: string
  tier: string
  tools: McpToolDefinition[]
}

interface McpState {
  /** User's local gateways (localStorage, this device only) */
  localGateways: McpGatewayConfig[]
  /** All discovered MCP tools for current session (set after discovery) */
  sessionTools: SessionToolEntry[]

  loadLocalGateways: () => void
  addLocalGateway: (gw: McpGatewayConfig) => void
  updateLocalGateway: (id: string, updates: Partial<McpGatewayConfig>) => void
  deleteLocalGateway: (id: string) => void
  setSessionTools: (tools: SessionToolEntry[]) => void
  clearSessionTools: () => void
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
  sessionTools: [],

  loadLocalGateways: () => {
    set({ localGateways: readLocalGateways() })
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

  setSessionTools: (tools) => set({ sessionTools: tools }),
  clearSessionTools: () => set({ sessionTools: [] }),
}))
