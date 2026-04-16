import { useEffect, useMemo, useState } from 'react'
import { AllowlistEditor } from './AllowlistEditor'
import { apiKeysApi } from './api'
import { ApiKeyCreateModal } from './ApiKeyCreateModal'
import { ApiKeyRevealModal } from './ApiKeyRevealModal'
import { useCommunityProvisioningStore } from './store'
import type { ApiKey } from './types'

/**
 * Renders the list of API-Keys for a homelab plus the create / regenerate /
 * revoke / allowlist actions. Lazy-loads the list the first time the
 * homelab card is expanded; WS events keep it fresh thereafter.
 */
export function ApiKeyList({ homelabId }: { homelabId: string }) {
  const apiKeysMap = useCommunityProvisioningStore(
    (s) => s.apiKeysByHomelab[homelabId],
  )
  const setApiKeys = useCommunityProvisioningStore((s) => s.setApiKeys)
  const apiKeys = useMemo(
    () => Object.values(apiKeysMap ?? {}),
    [apiKeysMap],
  )
  const [showCreate, setShowCreate] = useState(false)
  const [revealKey, setRevealKey] = useState<string | null>(null)
  const [editingAllowlistFor, setEditingAllowlistFor] = useState<ApiKey | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const list = await apiKeysApi.list(homelabId)
        if (!cancelled) setApiKeys(homelabId, list)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load API-Keys.')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [homelabId, setApiKeys])

  async function revoke(key: ApiKey) {
    const ok = window.confirm(
      `Revoke "${key.display_name}"? The consumer will lose access immediately.`,
    )
    if (!ok) return
    setError(null)
    setBusyId(key.api_key_id)
    try {
      await apiKeysApi.revoke(homelabId, key.api_key_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Revoke failed.')
    } finally {
      setBusyId(null)
    }
  }

  async function regenerate(key: ApiKey) {
    const ok = window.confirm(
      `Regenerate "${key.display_name}"? The consumer must update their connection with the new key before it will work again.`,
    )
    if (!ok) return
    setError(null)
    setBusyId(key.api_key_id)
    try {
      const res = await apiKeysApi.regenerate(homelabId, key.api_key_id)
      setRevealKey(res.plaintext_api_key)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Regenerate failed.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-[11px] font-mono uppercase tracking-wider text-white/60">
          API-Keys
        </h4>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="rounded bg-purple/70 px-2.5 py-1 text-[11px] text-white hover:bg-purple/80"
        >
          + API-Key
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
          {error}
        </div>
      )}

      {apiKeys.length === 0 ? (
        <p className="rounded border border-dashed border-white/10 p-3 text-center text-[12px] text-white/50">
          No API-Keys yet. Create one to hand out to a consumer.
        </p>
      ) : (
        <ul className="space-y-2">
          {apiKeys.map((k) => {
            const busy = busyId === k.api_key_id
            const revoked = k.status === 'revoked'
            return (
              <li
                key={k.api_key_id}
                className="flex items-center justify-between gap-3 rounded border border-white/8 bg-black/20 p-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13px] font-medium text-white/90">
                      {k.display_name}
                    </span>
                    {revoked && (
                      <span className="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-red-300">
                        revoked
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/40">
                    <span>
                      key …<code className="font-mono text-white/60">{k.api_key_hint}</code>
                    </span>
                    <span>·</span>
                    <span>
                      {k.allowed_model_slugs.length} model
                      {k.allowed_model_slugs.length === 1 ? '' : 's'} allowed
                    </span>
                  </div>
                </div>
                <div className="flex flex-shrink-0 items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingAllowlistFor(k)}
                    disabled={revoked}
                    className="rounded border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-40"
                  >
                    Edit allowlist
                  </button>
                  <button
                    type="button"
                    onClick={() => void regenerate(k)}
                    disabled={busy || revoked}
                    className="rounded border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-40"
                  >
                    Regenerate
                  </button>
                  <button
                    type="button"
                    onClick={() => void revoke(k)}
                    disabled={busy || revoked}
                    className="rounded border border-red-500/30 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/10 disabled:opacity-40"
                  >
                    Revoke
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {showCreate && (
        <ApiKeyCreateModal
          homelabId={homelabId}
          onClose={() => setShowCreate(false)}
          onCreated={(plaintext) => {
            setShowCreate(false)
            setRevealKey(plaintext)
          }}
        />
      )}
      {revealKey && (
        <ApiKeyRevealModal plaintext={revealKey} onClose={() => setRevealKey(null)} />
      )}
      {editingAllowlistFor && (
        <AllowlistEditor
          homelabId={homelabId}
          apiKey={editingAllowlistFor}
          onClose={() => setEditingAllowlistFor(null)}
        />
      )}
    </div>
  )
}
