import { useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { apiKeysApi } from './api'
import type { ApiKey } from './types'

/**
 * Explicit edit window for an API-Key. Surfaces the two fields safe for
 * in-place editing (display name + per-key concurrency). Model allowlist
 * lives in its own dedicated editor — keeping the surfaces separate avoids
 * a cramped combined dialog and keeps the "Edit allowlist" CTA findable.
 */
export function ApiKeyEditModal({
  homelabId,
  apiKey,
  onClose,
}: {
  homelabId: string
  apiKey: ApiKey
  onClose: () => void
}) {
  const [name, setName] = useState(apiKey.display_name)
  const [maxConcurrent, setMaxConcurrent] = useState<number>(apiKey.max_concurrent)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const trimmedName = name.trim()
  const nameInvalid = trimmedName.length < 1 || trimmedName.length > 80
  const concurrencyInvalid =
    !Number.isInteger(maxConcurrent) || maxConcurrent < 1 || maxConcurrent > 32

  const nameChanged = trimmedName !== apiKey.display_name
  const concurrencyChanged = maxConcurrent !== apiKey.max_concurrent
  const dirty = nameChanged || concurrencyChanged
  const canSubmit = !busy && dirty && !nameInvalid && !concurrencyInvalid

  async function submit() {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    try {
      await apiKeysApi.update(homelabId, apiKey.api_key_id, {
        ...(nameChanged ? { display_name: trimmedName } : {}),
        ...(concurrencyChanged ? { max_concurrent: maxConcurrent } : {}),
      })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="md"
      ariaLabel="Edit API-Key"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            Edit API-Key
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
        <div className="space-y-4 px-5 py-4">
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
                if (e.key === 'Enter' && canSubmit) void submit()
              }}
              maxLength={80}
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-gold/60"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
              Max parallel requests
            </label>
            <input
              type="number"
              min={1}
              max={32}
              value={maxConcurrent}
              onChange={(e) => setMaxConcurrent(Number(e.target.value))}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canSubmit) void submit()
              }}
              className="w-28 rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-gold/60"
            />
            <p className="text-[11px] text-white/50">
              How many simultaneous requests this API-Key can make.
            </p>
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
            disabled={!canSubmit}
            onClick={() => void submit()}
            className="rounded bg-gold/90 px-4 py-1.5 text-[12px] font-semibold text-black hover:bg-gold disabled:opacity-40"
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
