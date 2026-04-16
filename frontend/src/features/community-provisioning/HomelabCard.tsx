import { useState } from 'react'
import { ApiKeyList } from './ApiKeyList'
import { homelabsApi } from './api'
import { HostKeyRevealModal } from './HostKeyRevealModal'
import type { Homelab } from './types'

/**
 * Card representation of a single homelab. Shows live online/offline badge,
 * last-seen engine info, and surfaces the three host actions: rename,
 * regenerate host-key (with one-shot reveal), and delete.
 *
 * Inline rename via double-click mirrors the pattern in
 * `ConnectionConfigModal` (dedicated form) — here we keep it lightweight
 * because renaming is the only editable field.
 */
export function HomelabCard({ homelab }: { homelab: Homelab }) {
  const [expanded, setExpanded] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [nameDraft, setNameDraft] = useState(homelab.display_name)
  const [revealKey, setRevealKey] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function saveName() {
    const trimmed = nameDraft.trim()
    setRenaming(false)
    if (!trimmed || trimmed === homelab.display_name) {
      setNameDraft(homelab.display_name)
      return
    }
    setError(null)
    try {
      await homelabsApi.update(homelab.homelab_id, { display_name: trimmed })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rename failed.')
      setNameDraft(homelab.display_name)
    }
  }

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
          {renaming ? (
            <input
              autoFocus
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={() => void saveName()}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void saveName()
                if (e.key === 'Escape') {
                  setRenaming(false)
                  setNameDraft(homelab.display_name)
                }
              }}
              maxLength={80}
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1 text-sm text-white outline-none focus:border-gold/60"
            />
          ) : (
            <h3
              className="cursor-text truncate text-[14px] font-semibold text-white/90"
              onDoubleClick={() => setRenaming(true)}
              title="Double-click to rename"
            >
              {homelab.display_name}
            </h3>
          )}
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

      {revealKey && (
        <HostKeyRevealModal plaintext={revealKey} onClose={() => setRevealKey(null)} />
      )}
    </div>
  )
}
