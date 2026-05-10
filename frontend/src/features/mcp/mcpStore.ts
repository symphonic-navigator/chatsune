import { create } from 'zustand'
import { sendMessage } from '../../core/websocket/connection'
import { syncLocalGatewayToBackend } from './useMcpEvents'
import { namespaceFromName } from './_namespace'
import type { McpGatewayConfig, McpSessionGateway } from './types'

const LOCAL_STORAGE_KEY = 'chatsune:mcp_local_gateways'

interface McpState {
  /** User's local gateways (localStorage, this device only) */
  localGateways: McpGatewayConfig[]
  /** All discovered MCP gateways for current session (set after discovery) */
  sessionGateways: McpSessionGateway[]

  loadLocalGateways: () => void
  addLocalGateway: (gw: McpGatewayConfig) => Promise<void>
  updateLocalGateway: (id: string, updates: Partial<McpGatewayConfig>) => Promise<void>
  deleteLocalGateway: (id: string) => void
  setSessionGateways: (gateways: McpSessionGateway[]) => void
  clearSessionGateways: () => void

  // ── Streamable HTTP session lifecycle ─────────────────────
  sessions: Record<string, { sessionId: string | null | undefined; initialising: Promise<string | null> | null }>
  setSession: (url: string, sessionId: string | null) => void
  clearSession: (url: string) => void
  getSession: (url: string) => { sessionId: string | null | undefined; initialising: Promise<string | null> | null } | undefined
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

  addLocalGateway: async (gw) => {
    const updated = [...get().localGateways, gw]
    writeLocalGateways(updated)
    set({ localGateways: updated })

    const entry = await syncLocalGatewayToBackend(gw)
    if (entry) {
      set((s) => ({
        sessionGateways: [
          ...s.sessionGateways.filter((e) => e.namespace !== entry.namespace),
          entry,
        ],
      }))
    }
  },

  updateLocalGateway: async (id, updates) => {
    const previous = get().localGateways.find((gw) => gw.id === id)
    const updated = get().localGateways.map((gw) =>
      gw.id === id ? { ...gw, ...updates } : gw,
    )
    writeLocalGateways(updated)
    set({ localGateways: updated })

    const next = updated.find((gw) => gw.id === id)
    if (!next) return

    // Treat update as deregister + register so the namespace, URL, and
    // tool list are all refreshed cleanly (rename or URL change both
    // produce a fresh discovery).
    sendMessage({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: id },
    })

    // Drop the OLD session entry (matched by the previous name's
    // namespace). The new one will be appended on success below.
    const oldNs = previous ? namespaceFromName(previous.name) : null
    if (oldNs !== null) {
      set((s) => ({
        sessionGateways: s.sessionGateways.filter(
          (e) => !(e.tier === 'local' && e.namespace === oldNs),
        ),
      }))
    }

    const entry = await syncLocalGatewayToBackend(next)
    if (entry) {
      set((s) => ({
        sessionGateways: [
          ...s.sessionGateways.filter((e) => e.namespace !== entry.namespace),
          entry,
        ],
      }))
    }
  },

  deleteLocalGateway: (id) => {
    const removed = get().localGateways.find((gw) => gw.id === id)
    if (!removed) return

    const updated = get().localGateways.filter((gw) => gw.id !== id)
    writeLocalGateways(updated)
    const ns = namespaceFromName(removed.name)
    set((s) => ({
      localGateways: updated,
      sessionGateways: s.sessionGateways.filter(
        (e) => !(e.tier === 'local' && e.namespace === ns),
      ),
    }))

    sendMessage({
      type: 'mcp.tools.deregister',
      payload: { gateway_id: id },
    })
  },

  setSessionGateways: (gateways) => set({ sessionGateways: gateways }),
  clearSessionGateways: () => set({ sessionGateways: [] }),

  sessions: {},
  setSession: (url, sessionId) =>
    set((s) => ({
      sessions: { ...s.sessions, [url]: { sessionId, initialising: null } },
    })),
  clearSession: (url) =>
    set((s) => {
      if (!(url in s.sessions)) return {}
      const next = { ...s.sessions }
      delete next[url]
      return { sessions: next }
    }),
  getSession: (url) => get().sessions[url],
}))
