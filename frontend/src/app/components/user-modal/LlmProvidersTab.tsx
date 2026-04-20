import { useCallback, useEffect, useState } from 'react'
import { useProvidersStore } from '../../../core/store/providersStore'
import { CoverageRow } from '../providers/CoverageRow'
import { PremiumAccountCard } from '../providers/PremiumAccountCard'
import { llmApi } from '../../../core/api/llm'
import type { Connection } from '../../../core/types/llm'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'
import { ConnectionListItem } from '../llm-providers/ConnectionListItem'
import { AddConnectionWizard } from '../llm-providers/AddConnectionWizard'
import { ConnectionConfigModal } from '../llm-providers/ConnectionConfigModal'

export function LlmProvidersTab() {
  // Premium provider accounts — sourced from the providersStore.
  const catalogue = useProvidersStore((s) => s.catalogue)
  const accounts = useProvidersStore((s) => s.accounts)
  const premiumLoading = useProvidersStore((s) => s.loading)
  const premiumError = useProvidersStore((s) => s.error)
  const refreshPremium = useProvidersStore((s) => s.refresh)
  const savePremium = useProvidersStore((s) => s.save)
  const removePremium = useProvidersStore((s) => s.remove)
  const configuredIds = useProvidersStore((s) => s.configuredIds)
  const coveredCapabilities = useProvidersStore((s) => s.coveredCapabilities)

  useEffect(() => {
    void refreshPremium()
  }, [refreshPremium])

  // Re-fetch premium accounts whenever any server-side change fires. We
  // always re-list rather than patching from event payloads so the canonical
  // server view wins (handles concurrent edits and ordering anomalies).
  useEffect(() => {
    const topics = [
      Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refreshPremium() }))
    return () => unsubs.forEach((u) => u())
  }, [refreshPremium])

  // Local & Homelab connection list — preserves the previous behaviour.
  const [connections, setConnections] = useState<Connection[]>([])
  const [connectionsLoading, setConnectionsLoading] = useState(true)
  const [connectionsError, setConnectionsError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [editing, setEditing] = useState<Connection | null>(null)

  const refreshConnections = useCallback(async () => {
    setConnectionsError(null)
    try {
      const next = await llmApi.listConnections()
      setConnections(next)
      // Keep the in-flight edit modal in sync with the latest payload so
      // server-side updates (e.g. last_test_status flips) flow into the form.
      setEditing((cur) => (cur ? next.find((c) => c.id === cur.id) ?? null : cur))
    } catch (err) {
      setConnectionsError(
        err instanceof Error ? err.message : 'Could not load connections.',
      )
    } finally {
      setConnectionsLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshConnections()
  }, [refreshConnections])

  // Live-sync: any connection-state event triggers a re-fetch. Skipping
  // LLM_CONNECTION_TESTED — the backend follows it with LLM_CONNECTION_UPDATED
  // which we're already subscribed to.
  useEffect(() => {
    const topics = [
      Topics.LLM_CONNECTION_CREATED,
      Topics.LLM_CONNECTION_UPDATED,
      Topics.LLM_CONNECTION_REMOVED,
      Topics.LLM_CONNECTION_STATUS_CHANGED,
      Topics.LLM_CONNECTION_MODELS_REFRESHED,
    ] as const
    const unsubs = topics.map((t) =>
      eventBus.on(t, () => { void refreshConnections() }),
    )
    return () => unsubs.forEach((u) => u())
  }, [refreshConnections])

  // Coverage row inputs — derived from catalogue + configured accounts.
  const configured = configuredIds()
  const byCapability = new Map<string, string[]>()
  for (const d of catalogue) {
    if (configured.has(d.id)) {
      for (const c of d.capabilities) {
        const arr = byCapability.get(c) ?? []
        arr.push(d.display_name)
        byCapability.set(c, arr)
      }
    }
  }

  // Split the flat connection list into two visually distinct groups.
  // Self-hosted connections (homelab self-connections) are owned by the
  // Homelab module — non-interactive, pointed at the Homelabs page. The
  // rest are ordinary user-managed local / homelab provider connections.
  const selfHosted = connections.filter((c) => c.is_system_managed === true)
  const localAndHomelab = connections.filter((c) => c.is_system_managed !== true)

  // Initial whole-tab loading state — only while both sources are still
  // in their first fetch and have no data to show yet.
  if (
    premiumLoading &&
    connectionsLoading &&
    accounts.length === 0 &&
    catalogue.length === 0 &&
    connections.length === 0
  ) {
    return <div className="p-6 text-sm text-white/60">Loading…</div>
  }

  // Fatal errors — either side blocks rendering so the user sees the
  // problem rather than a half-populated tab.
  if (premiumError || connectionsError) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-red-300">
          {premiumError ?? connectionsError}
        </p>
        <button
          type="button"
          onClick={() => {
            if (premiumError) void refreshPremium()
            if (connectionsError) {
              setConnectionsLoading(true)
              void refreshConnections()
            }
          }}
          className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
        >
          Try again
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        <CoverageRow
          covered={coveredCapabilities()}
          providersByCapability={byCapability}
        />

        <section className="px-6 py-4 space-y-3">
          <h3 className="text-[11px] font-mono uppercase tracking-wider text-white/40">
            Accounts
          </h3>
          {catalogue.length === 0 ? (
            <p className="text-[11px] text-white/40">
              No premium providers available.
            </p>
          ) : (
            catalogue.map((d) => {
              const acct = accounts.find((a) => a.provider_id === d.id) ?? null
              return (
                <PremiumAccountCard
                  key={d.id}
                  definition={d}
                  account={acct}
                  onSave={(cfg) => savePremium(d.id, cfg)}
                  onDelete={() => removePremium(d.id)}
                  onTest={async () => {
                    // No dedicated /test endpoint today; a re-save with the
                    // same config triggers the backend test path once added.
                    // Placeholder for now — wire when a /test endpoint lands
                    // in a follow-up.
                  }}
                />
              )
            })
          )}
        </section>

        {selfHosted.length > 0 && (
          <section className="px-6 py-4 space-y-3">
            <div>
              <h3 className="text-[11px] font-mono uppercase tracking-wider text-white/40">
                Self-Hosted
              </h3>
              <p className="mt-1 text-[11px] text-white/50">
                Your own homelab compute. Manage it under Homelabs.
              </p>
            </div>
            <ul className="divide-y divide-white/5">
              {selfHosted.map((c) => (
                <ConnectionListItem
                  key={c.id}
                  connection={c}
                  isSelfHosted
                  onClick={() => setEditing(c)}
                />
              ))}
            </ul>
          </section>
        )}

        <section className="px-6 py-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-mono uppercase tracking-wider text-white/40">
              Local &amp; Homelab
            </h3>
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5"
            >
              + Add
            </button>
          </div>
          {localAndHomelab.length === 0 ? (
            <p className="text-[11px] text-white/40">
              No local or homelab connections configured yet.
            </p>
          ) : (
            <ul className="divide-y divide-white/5">
              {localAndHomelab.map((c) => (
                <ConnectionListItem
                  key={c.id}
                  connection={c}
                  onClick={() => setEditing(c)}
                />
              ))}
            </ul>
          )}
        </section>
      </div>

      {wizardOpen && (
        <AddConnectionWizard
          onClose={() => setWizardOpen(false)}
          onCreated={async () => {
            // Refresh the connection list; the modal controls its own closing.
            await refreshConnections()
          }}
        />
      )}
      {editing && (
        <ConnectionConfigModal
          connection={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            // Refresh the connection list; the modal controls its own closing.
            await refreshConnections()
          }}
          onDeleted={async () => {
            setEditing(null)
            await refreshConnections()
          }}
        />
      )}
    </div>
  )
}
