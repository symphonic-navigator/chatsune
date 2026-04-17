import { useCallback, useEffect, useState } from 'react'
import { llmApi } from '../../../core/api/llm'
import type { Connection } from '../../../core/types/llm'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'
import { ConnectionListItem } from '../llm-providers/ConnectionListItem'
import { AddConnectionWizard } from '../llm-providers/AddConnectionWizard'
import { ConnectionConfigModal } from '../llm-providers/ConnectionConfigModal'

export function LlmProvidersTab() {
  const [items, setItems] = useState<Connection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [editing, setEditing] = useState<Connection | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const next = await llmApi.listConnections()
      setItems(next)
      // Keep the in-flight edit modal in sync with the latest payload so
      // server-side updates (e.g. last_test_status flips) flow into the form.
      setEditing((cur) => (cur ? next.find((c) => c.id === cur.id) ?? null : cur))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load connections.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Live-sync: any connection-state event triggers a re-fetch. We deliberately
  // re-list rather than patching from the event payload so the displayed state
  // always matches the canonical server view (handles concurrent admin edits,
  // partial events, and ordering anomalies). Skipping LLM_CONNECTION_TESTED —
  // the backend follows it with LLM_CONNECTION_UPDATED that carries the new
  // last_test_status, which we're already subscribed to.
  useEffect(() => {
    const topics = [
      Topics.LLM_CONNECTION_CREATED,
      Topics.LLM_CONNECTION_UPDATED,
      Topics.LLM_CONNECTION_REMOVED,
      Topics.LLM_CONNECTION_STATUS_CHANGED,
      Topics.LLM_CONNECTION_MODELS_REFRESHED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refresh() }))
    return () => unsubs.forEach((u) => u())
  }, [refresh])

  if (loading) {
    return <div className="p-6 text-sm text-white/60">Loading…</div>
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-red-300">{error}</p>
        <button
          type="button"
          onClick={() => { setLoading(true); void refresh() }}
          className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
        >
          Try again
        </button>
      </div>
    )
  }

  // Split the flat connection list into two visually distinct groups. Self-
  // hosted connections (homelab self-connections) are owned by the Homelab
  // module — they render first, non-interactive, with guidance pointing at
  // the Homelabs page. Everything else is an ordinary user-managed provider.
  const selfHosted = items.filter((c) => c.is_system_managed === true)
  const providers = items.filter((c) => c.is_system_managed !== true)

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 p-10 text-center">
        <p className="text-white/70">No LLM connection configured yet.</p>
        <button
          type="button"
          onClick={() => setWizardOpen(true)}
          className="rounded bg-purple/70 px-4 py-2 text-sm text-white hover:bg-purple/80"
        >
          Set up connection
        </button>
        {wizardOpen && (
          <AddConnectionWizard
            onClose={() => setWizardOpen(false)}
            onCreated={async () => {
              setWizardOpen(false)
              await refresh()
            }}
          />
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto">
        {selfHosted.length > 0 && (
          <div>
            <div className="border-b border-white/6 px-5 py-3">
              <h3 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
                Self-Hosted
              </h3>
              <p className="mt-1 text-[11px] text-white/50">
                Your own homelab compute. Manage it under Homelabs.
              </p>
            </div>
            <ul className="divide-y divide-white/5 px-2 py-2">
              {selfHosted.map((c) => (
                <ConnectionListItem
                  key={c.id}
                  connection={c}
                  isSelfHosted
                  onClick={() => setEditing(c)}
                />
              ))}
            </ul>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
            <h3 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
              Providers
            </h3>
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="rounded bg-purple/70 px-3 py-1 text-[12px] text-white hover:bg-purple/80"
            >
              + Connection
            </button>
          </div>
          {providers.length === 0 ? (
            <p className="px-5 py-4 text-[12px] text-white/50">
              No provider connections yet.
            </p>
          ) : (
            <ul className="divide-y divide-white/5 px-2 py-2">
              {providers.map((c) => (
                <ConnectionListItem
                  key={c.id}
                  connection={c}
                  onClick={() => setEditing(c)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>

      {wizardOpen && (
        <AddConnectionWizard
          onClose={() => setWizardOpen(false)}
          onCreated={async () => {
            // Refresh the connection list; the modal controls its own closing.
            await refresh()
          }}
        />
      )}
      {editing && (
        <ConnectionConfigModal
          connection={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            // Refresh the connection list; the modal controls its own closing.
            await refresh()
          }}
          onDeleted={async () => {
            setEditing(null)
            await refresh()
          }}
        />
      )}
    </div>
  )
}
