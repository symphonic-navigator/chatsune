import { useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { apiKeysApi } from './api'

/**
 * Collects a display name and creates a fresh API-Key. By design the new
 * key starts with an empty allowlist (no "tick all" convenience) — the
 * host then ticks models explicitly in the `AllowlistEditor`.
 *
 * On success the caller receives the plaintext key and is responsible
 * for rendering `ApiKeyRevealModal` — keeps this modal narrowly scoped.
 */
export function ApiKeyCreateModal({
  homelabId,
  onClose,
  onCreated,
}: {
  homelabId: string
  onClose: () => void
  onCreated: (plaintext: string) => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      const res = await apiKeysApi.create(homelabId, {
        display_name: trimmed,
        allowed_model_slugs: [],
      })
      onCreated(res.plaintext_api_key)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Create failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="md"
      ariaLabel="Create API-Key"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            Create API-Key
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70"
          >
            ✕
          </button>
        </div>
        <div className="space-y-3 px-5 py-4">
          <p className="text-[12px] text-white/60">
            Give it a name that tells you who it's for. The new key starts
            with no models allowed — tick models explicitly afterwards via
            "Edit allowlist".
          </p>
          <div className="space-y-1">
            <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
              Display name
            </label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !busy && name.trim()) void submit()
              }}
              maxLength={80}
              placeholder="e.g. Bob (Testphase)"
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-gold/60"
            />
          </div>
          {error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {error}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-white/8 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="text-[12px] text-white/60 hover:text-white/80"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={busy || !name.trim()}
            onClick={() => void submit()}
            className="rounded bg-gold/90 px-4 py-1.5 text-[12px] font-semibold text-black hover:bg-gold disabled:opacity-40"
          >
            {busy ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
