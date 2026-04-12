import { useCallback, useEffect, useState } from 'react'
import { mcpApi } from '../../../features/mcp/mcpApi'
import { useMcpStore } from '../../../features/mcp/mcpStore'
import { GatewayEditDialog } from '../../../features/mcp/GatewayEditDialog'
import { ToolExplorer } from '../../../features/mcp/ToolExplorer'
import type { McpGatewayConfig } from '../../../features/mcp/types'

// ─── colour tokens ────────────────────────────────────────────────────────────
const REMOTE_ACCENT = 'rgba(166,218,149,1)'
const LOCAL_ACCENT  = 'rgba(245,194,131,1)'
const ADMIN_ACCENT  = 'rgba(140,118,215,1)'

const REMOTE_DOT_ON  = 'rgba(166,218,149,0.9)'
const LOCAL_DOT_ON   = 'rgba(245,194,131,0.9)'

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`

// ─── types ────────────────────────────────────────────────────────────────────

type View =
  | { kind: 'list' }
  | { kind: 'edit-remote'; gateway?: McpGatewayConfig }
  | { kind: 'edit-local'; gateway?: McpGatewayConfig }
  | { kind: 'explore'; gateway: McpGatewayConfig; tier: 'admin' | 'remote' | 'local' }

// ─── GatewayCard ──────────────────────────────────────────────────────────────

interface GatewayCardProps {
  gateway: McpGatewayConfig
  dotColour: string
  readonly: boolean
  onExplore: () => void
  onEdit?: () => void
}

function GatewayCard({ gateway, dotColour, readonly, onExplore, onEdit }: GatewayCardProps) {
  return (
    <div
      className="flex items-center gap-3 px-3 py-2.5 border-b border-white/5 hover:bg-white/[0.025] transition-colors"
      style={{ opacity: gateway.enabled ? 1 : 0.5 }}
    >
      {/* status dot */}
      <span
        className="flex-shrink-0 h-2 w-2 rounded-full"
        style={{ background: gateway.enabled ? dotColour : 'rgba(255,255,255,0.2)' }}
        aria-label={gateway.enabled ? 'Enabled' : 'Disabled'}
      />

      {/* name + url */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[12px] text-white/80 font-medium truncate">{gateway.name}</span>
          {!gateway.enabled && (
            <span className="text-[9px] uppercase tracking-wider border border-white/10 text-white/30 rounded px-1 py-0.5 font-mono">
              disabled
            </span>
          )}
        </div>
        <div className="text-[11px] font-mono text-white/30 truncate mt-0.5">{gateway.url}</div>
      </div>

      {/* actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <button type="button" onClick={onExplore} className={BTN_NEUTRAL} title="Explore tools">
          Explore
        </button>
        {!readonly && onEdit && (
          <button type="button" onClick={onEdit} className={BTN_NEUTRAL} title="Edit gateway">
            Edit
          </button>
        )}
      </div>
    </div>
  )
}

// ─── SectionHeader ────────────────────────────────────────────────────────────

function SectionHeader({
  label,
  accent,
  subtitle,
  onAdd,
}: {
  label: string
  accent: string
  subtitle?: string
  onAdd?: () => void
}) {
  return (
    <div className="flex items-start justify-between px-3 py-3 border-b border-white/6">
      <div>
        <span className="text-[11px] font-mono uppercase tracking-wider" style={{ color: accent }}>
          {label}
        </span>
        {subtitle && <p className="text-[10px] text-white/30 mt-0.5">{subtitle}</p>}
      </div>
      {onAdd && (
        <button
          type="button"
          onClick={onAdd}
          className={`${BTN} border-white/10 text-white/40 hover:text-white/60 hover:border-white/20`}
          title={`Add ${label} gateway`}
        >
          + Add
        </button>
      )}
    </div>
  )
}

// ─── McpTab ───────────────────────────────────────────────────────────────────

export function McpTab() {
  const [view, setView] = useState<View>({ kind: 'list' })

  // remote gateways (server-side, per-user)
  const [remoteGateways, setRemoteGateways] = useState<McpGatewayConfig[]>([])
  const [remoteLoading, setRemoteLoading] = useState(true)
  const [remoteError, setRemoteError] = useState<string | null>(null)

  // admin gateways (server-side, read-only)
  const [adminGateways, setAdminGateways] = useState<McpGatewayConfig[]>([])
  // 403 is expected for non-admin users — we just hide the section
  const [adminForbidden, setAdminForbidden] = useState(false)

  // local gateways from store (localStorage)
  const { localGateways, loadLocalGateways } = useMcpStore()

  // ── load remote gateways ──
  const fetchRemote = useCallback(async () => {
    setRemoteLoading(true)
    setRemoteError(null)
    try {
      const gws = await mcpApi.listGateways()
      setRemoteGateways(gws)
    } catch {
      setRemoteError('Could not load remote gateways.')
    } finally {
      setRemoteLoading(false)
    }
  }, [])

  // ── load admin gateways ──
  const fetchAdmin = useCallback(async () => {
    try {
      const gws = await mcpApi.listAdminGateways()
      setAdminGateways(gws)
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 403) {
        setAdminForbidden(true)
      }
      // silently ignore other errors — admin section is best-effort
    }
  }, [])

  useEffect(() => {
    loadLocalGateways()
    fetchRemote()
    fetchAdmin()
  }, [fetchRemote, fetchAdmin, loadLocalGateways])

  // ── handle ToolExplorer toggle (disabled_tools) ──
  function handleToggleTool(gateway: McpGatewayConfig, tier: 'remote' | 'local', toolName: string, disable: boolean) {
    const updated: McpGatewayConfig = {
      ...gateway,
      disabled_tools: disable
        ? [...gateway.disabled_tools, toolName]
        : gateway.disabled_tools.filter((t) => t !== toolName),
    }
    if (tier === 'remote') {
      mcpApi.updateGateway(gateway.id, { disabled_tools: updated.disabled_tools }).then(() => {
        setRemoteGateways((prev) => prev.map((g) => (g.id === gateway.id ? updated : g)))
      })
      // optimistic update
      setRemoteGateways((prev) => prev.map((g) => (g.id === gateway.id ? updated : g)))
    } else {
      useMcpStore.getState().updateLocalGateway(gateway.id, { disabled_tools: updated.disabled_tools })
    }
  }

  // ── save handlers for remote gateways ──
  async function handleSaveRemote(data: McpGatewayConfig, original?: McpGatewayConfig) {
    if (original) {
      await mcpApi.updateGateway(original.id, data)
    } else {
      await mcpApi.createGateway({
        name: data.name,
        url: data.url,
        api_key: data.api_key,
        enabled: data.enabled,
      })
    }
    await fetchRemote()
    setView({ kind: 'list' })
  }

  async function handleDeleteRemote(id: string) {
    await mcpApi.deleteGateway(id)
    await fetchRemote()
    setView({ kind: 'list' })
  }

  // ── save handlers for local gateways ──
  function handleSaveLocal(data: McpGatewayConfig, original?: McpGatewayConfig) {
    if (original) {
      useMcpStore.getState().updateLocalGateway(original.id, data)
    } else {
      useMcpStore.getState().addLocalGateway({
        ...data,
        id: crypto.randomUUID(),
      })
    }
    setView({ kind: 'list' })
  }

  function handleDeleteLocal(id: string) {
    useMcpStore.getState().deleteLocalGateway(id)
    setView({ kind: 'list' })
  }

  // ─── sub-views ─────────────────────────────────────────────────────────────

  if (view.kind === 'explore') {
    const { gateway, tier } = view
    return (
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        <ToolExplorer
          gateway={gateway}
          tier={tier}
          onBack={() => setView({ kind: 'list' })}
          onToggleTool={(toolName, disable) => {
            if (tier === 'admin') return // read-only
            handleToggleTool(gateway, tier as 'remote' | 'local', toolName, disable)
          }}
        />
      </div>
    )
  }

  if (view.kind === 'edit-remote') {
    const existing = view.gateway
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="px-4 pt-4 pb-6 max-w-lg">
          <p className="text-[11px] text-white/40 mb-3">
            {existing ? 'Edit remote gateway' : 'Add remote gateway'}
          </p>
          <GatewayEditDialog
            mode={existing ? 'edit' : 'create'}
            gateway={existing}
            tier="remote"
            onSave={(data) => handleSaveRemote(data, existing)}
            onDelete={existing ? () => handleDeleteRemote(existing.id) : undefined}
            onCancel={() => setView({ kind: 'list' })}
          />
        </div>
      </div>
    )
  }

  if (view.kind === 'edit-local') {
    const existing = view.gateway
    return (
      <div className="flex-1 overflow-y-auto">
        <div className="px-4 pt-4 pb-6 max-w-lg">
          <p className="text-[11px] text-white/40 mb-3">
            {existing ? 'Edit local gateway' : 'Add local gateway'}
          </p>
          <GatewayEditDialog
            mode={existing ? 'edit' : 'create'}
            gateway={existing}
            tier="local"
            onSave={(data) => handleSaveLocal(data, existing)}
            onDelete={existing ? () => handleDeleteLocal(existing.id) : undefined}
            onCancel={() => setView({ kind: 'list' })}
          />
        </div>
      </div>
    )
  }

  // ─── list view ─────────────────────────────────────────────────────────────

  return (
    <div className="flex-1 overflow-y-auto">

      {/* ── Remote Gateways ── */}
      <section>
        <SectionHeader
          label="Remote Gateways"
          accent={REMOTE_ACCENT}
          onAdd={() => setView({ kind: 'edit-remote' })}
        />

        {remoteLoading && (
          <div className="flex items-center justify-center py-6">
            <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/10 border-t-white/40" />
          </div>
        )}

        {remoteError && !remoteLoading && (
          <div className="mx-3 my-3 rounded-lg border border-red-400/15 bg-red-400/5 px-3 py-2 text-[11px] text-red-400">
            {remoteError}
            <button type="button" onClick={fetchRemote} className="ml-2 underline text-red-300 hover:text-red-200">
              Retry
            </button>
          </div>
        )}

        {!remoteLoading && !remoteError && remoteGateways.length === 0 && (
          <p className="px-3 py-3 text-[11px] text-white/25 italic">No remote gateways configured.</p>
        )}

        {!remoteLoading && remoteGateways.map((gw) => (
          <GatewayCard
            key={gw.id}
            gateway={gw}
            dotColour={REMOTE_DOT_ON}
            readonly={false}
            onExplore={() => setView({ kind: 'explore', gateway: gw, tier: 'remote' })}
            onEdit={() => setView({ kind: 'edit-remote', gateway: gw })}
          />
        ))}
      </section>

      {/* ── Local Gateways ── */}
      <section className="mt-2">
        <SectionHeader
          label="Local Gateways"
          accent={LOCAL_ACCENT}
          subtitle="This device only — stored in browser"
          onAdd={() => setView({ kind: 'edit-local' })}
        />

        {localGateways.length === 0 && (
          <p className="px-3 py-3 text-[11px] text-white/25 italic">No local gateways configured.</p>
        )}

        {localGateways.map((gw) => (
          <GatewayCard
            key={gw.id}
            gateway={gw}
            dotColour={LOCAL_DOT_ON}
            readonly={false}
            onExplore={() => setView({ kind: 'explore', gateway: gw, tier: 'local' })}
            onEdit={() => setView({ kind: 'edit-local', gateway: gw })}
          />
        ))}
      </section>

      {/* ── Global / Admin Gateways ── */}
      {!adminForbidden && (
        <section className="mt-2">
          <SectionHeader
            label="Global Gateways"
            accent={ADMIN_ACCENT}
            subtitle="Managed by admin — available to all users"
          />

          {adminGateways.length === 0 && (
            <p className="px-3 py-3 text-[11px] text-white/25 italic">No global gateways configured.</p>
          )}

          {adminGateways.map((gw) => (
            <GatewayCard
              key={gw.id}
              gateway={gw}
              dotColour={ADMIN_ACCENT}
              readonly={true}
              onExplore={() => setView({ kind: 'explore', gateway: gw, tier: 'admin' })}
            />
          ))}
        </section>
      )}
    </div>
  )
}
