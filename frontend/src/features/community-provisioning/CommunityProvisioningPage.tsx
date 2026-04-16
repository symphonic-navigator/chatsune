import { useEffect, useState } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { homelabsApi } from './api'
import { handleCommunityProvisioningEvent } from './events'
import { HomelabCreateModal } from './HomelabCreateModal'
import { HomelabList } from './HomelabList'
import { useCommunityProvisioningStore } from './store'

/**
 * Top-level page for the Community Provisioning Settings section.
 *
 * Responsibilities:
 *   - One-shot fetch of the homelab list on mount (subsequent updates flow
 *     in through WS events).
 *   - Subscribe the store to the nine `llm.homelab.*` / `llm.api_key.*`
 *     topics emitted by the backend. Subscribing here (not at app startup)
 *     keeps listener count low for users who never open this page.
 *   - Render the "Create homelab" primary action and the list.
 */
export function CommunityProvisioningPage() {
  const homelabs = useCommunityProvisioningStore((s) => Object.values(s.homelabs))
  const loaded = useCommunityProvisioningStore((s) => s.loaded)
  const setHomelabs = useCommunityProvisioningStore((s) => s.setHomelabs)
  const [showCreate, setShowCreate] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (loaded) return
    let cancelled = false
    void (async () => {
      try {
        const list = await homelabsApi.list()
        if (!cancelled) setHomelabs(list)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load homelabs.')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loaded, setHomelabs])

  useEffect(() => {
    const topics = [
      'llm.homelab.created',
      'llm.homelab.updated',
      'llm.homelab.deleted',
      'llm.homelab.host_key_regenerated',
      'llm.homelab.status_changed',
      'llm.homelab.last_seen',
      'llm.api_key.created',
      'llm.api_key.updated',
      'llm.api_key.revoked',
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, handleCommunityProvisioningEvent))
    return () => unsubs.forEach((u) => u())
  }, [])

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-start justify-between gap-4 border-b border-white/6 px-5 py-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            Community Provisioning
          </h3>
          <p className="mt-1 max-w-prose text-[12px] text-white/50">
            Share your home compute with people you invite. Run the Chatsune
            Sidecar on your GPU box, register it here, and issue API-Keys to
            the people you want to share with.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="flex-shrink-0 rounded bg-gold/90 px-3 py-1 text-[12px] font-semibold text-black hover:bg-gold"
        >
          + Homelab
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {error && (
          <div className="mb-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
            {error}
          </div>
        )}
        <HomelabList homelabs={homelabs} />
      </div>

      {showCreate && <HomelabCreateModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}
