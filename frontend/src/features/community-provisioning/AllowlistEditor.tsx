import { useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { apiKeysApi } from './api'
import type { ApiKey } from './types'

/**
 * Minimum-viable allowlist editor for an API-Key: free-form slug entry,
 * remove buttons, save. Once Plan 4 (community adapter) ships, this will
 * be upgraded to fetch the live model list from the host's own community
 * connection and present tickable checkboxes — see the parent plan's
 * Task 7 note.
 */
export function AllowlistEditor({
  homelabId,
  apiKey,
  onClose,
}: {
  homelabId: string
  apiKey: ApiKey
  onClose: () => void
}) {
  const [slugs, setSlugs] = useState<string[]>([...apiKey.allowed_model_slugs])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function add() {
    const v = draft.trim()
    if (!v) return
    if (!slugs.includes(v)) setSlugs((xs) => [...xs, v])
    setDraft('')
  }

  function remove(s: string) {
    setSlugs((xs) => xs.filter((x) => x !== s))
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await apiKeysApi.update(homelabId, apiKey.api_key_id, {
        allowed_model_slugs: slugs,
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
      size="xl"
      ariaLabel="Edit allowlist"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            Allowed models — <span className="text-white/80">{apiKey.display_name}</span>
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
          <p className="text-[12px] text-white/60">
            Only models in this list will be visible to the consumer using
            this API-Key. Enter each model's slug exactly as it appears in
            your sidecar — for example{' '}
            <code className="rounded bg-black/40 px-1 font-mono">llama3.2:8b</code>.
          </p>

          <div className="flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  add()
                }
              }}
              placeholder="llama3.2:8b"
              className="flex-1 rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-gold/60"
            />
            <button
              type="button"
              onClick={add}
              disabled={!draft.trim()}
              className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5 disabled:opacity-40"
            >
              Add
            </button>
          </div>

          {slugs.length === 0 ? (
            <div className="rounded border border-dashed border-white/15 p-3 text-center text-[12px] text-white/50">
              No models allowed. The consumer will see an empty model list.
            </div>
          ) : (
            <ul className="space-y-2">
              {slugs.map((s) => (
                <li
                  key={s}
                  className="flex items-center justify-between rounded border border-white/8 bg-black/30 p-2"
                >
                  <code className="font-mono text-[12px] text-white/80">{s}</code>
                  <button
                    type="button"
                    onClick={() => remove(s)}
                    className="rounded border border-red-500/30 px-2 py-0.5 text-[11px] text-red-300 hover:bg-red-500/10"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}

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
            disabled={busy}
            onClick={() => void save()}
            className="rounded bg-gold/90 px-4 py-1.5 text-[12px] font-semibold text-black hover:bg-gold disabled:opacity-40"
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
