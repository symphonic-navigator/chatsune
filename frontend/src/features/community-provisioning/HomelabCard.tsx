import { useState } from 'react'
import { ApiKeyList } from './ApiKeyList'
import { homelabsApi } from './api'
import { HomelabEditModal } from './HomelabEditModal'
import { HostKeyRevealModal } from './HostKeyRevealModal'
import type { Homelab } from './types'

/**
 * Card representation of a single homelab. Shows live online/offline badge,
 * last-seen engine info, and surfaces the host actions: edit (display name
 * + max concurrency), regenerate host-key (with one-shot reveal), and
 * delete.
 */
export function HomelabCard({ homelab }: { homelab: Homelab }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [revealKey, setRevealKey] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function regenerate() {
    const ok = window.confirm(
      'Generate a new Host-Key? The running sidecar will drop until you update its .env with the new key.',
    )
    if (!ok) return
    setError(null)
    setBusy(true)
    try {
      const res = await homelabsApi.regenerateHostKey(homelab.homelab_id)
      setRevealKey(res.plaintext_host_key)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Regenerate failed.')
    } finally {
      setBusy(false)
    }
  }

  async function del() {
    const ok = window.confirm(
      `Delete "${homelab.display_name}"? All API-Keys will be revoked and every consumer connection pointing here will break.`,
    )
    if (!ok) return
    setError(null)
    setBusy(true)
    try {
      await homelabsApi.delete(homelab.homelab_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete failed.')
      setBusy(false)
    }
  }

  const online = homelab.is_online
  const engine = homelab.last_engine_info

  return (
    <div className="rounded border border-white/8 bg-white/[0.03] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[14px] font-semibold text-white/90">
            {homelab.display_name}
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-white/40">
            <code className="font-mono text-white/60">{homelab.homelab_id}</code>
            <span>·</span>
            <span>
              host-key …<code className="font-mono text-white/60">{homelab.host_key_hint}</code>
            </span>
            <span
              className={[
                'rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider',
                online
                  ? 'border-green-500/30 bg-green-500/10 text-green-300'
                  : 'border-white/15 bg-white/5 text-white/40',
              ].join(' ')}
            >
              {online ? 'online' : 'offline'}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-white/40">
            Max parallel{' '}
            <span className="text-white/60">{homelab.max_concurrent_requests}</span>
            {homelab.host_slug && (
              <>
                <span className="mx-1">·</span>
                Self-slug{' '}
                <code className="font-mono text-white/60">{homelab.host_slug}</code>
              </>
            )}
          </div>
          {engine && (
            <div className="mt-1 text-[11px] text-white/40">
              Engine: <span className="text-white/60">{engine.type}</span>
              {engine.version && <span> {engine.version}</span>}
              {homelab.last_sidecar_version && (
                <span className="ml-2">
                  · Sidecar{' '}
                  <span className="text-white/60">{homelab.last_sidecar_version}</span>
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setExpanded((x) => !x)}
            className="rounded border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/5"
          >
            {expanded ? 'Hide keys' : 'Manage keys'}
          </button>
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={busy}
            className="rounded border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-40"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => void regenerate()}
            disabled={busy}
            className="rounded border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-40"
          >
            Regenerate host-key
          </button>
          <button
            type="button"
            onClick={() => void del()}
            disabled={busy}
            className="rounded border border-red-500/30 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/10 disabled:opacity-40"
          >
            Delete
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
          {error}
        </div>
      )}

      {expanded && (
        <div className="mt-4 border-t border-white/6 pt-4">
          <ApiKeyList homelabId={homelab.homelab_id} />
        </div>
      )}

      {editing && (
        <HomelabEditModal homelab={homelab} onClose={() => setEditing(false)} />
      )}
      {revealKey && (
        <HostKeyRevealModal plaintext={revealKey} onClose={() => setRevealKey(null)} />
      )}
    </div>
  )
}
