import { useEffect, useMemo, useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { apiKeysApi, homelabsApi, type HomelabSidecarModel } from './api'
import type { ApiKey } from './types'

/**
 * Per-API-Key allowlist editor.
 *
 * When the sidecar is online it renders the live model list as a tickable
 * checkbox list. When the sidecar is offline it falls back to a read-only
 * view of the currently-allowed slugs plus free-form entry, so a host can
 * still edit the allowlist without their GPU box being reachable.
 *
 * No implicit "tick everything" affordance — the design explicitly requires
 * every slug to be picked by hand (see
 * docs/superpowers/specs/2026-04-16-community-provisioning-design.md §7.4).
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [models, setModels] = useState<HomelabSidecarModel[] | null>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await homelabsApi.listModels(homelabId)
        if (cancelled) return
        setOnline(res.online)
        setModels(res.models)
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Could not load models.')
          setOnline(false)
          setModels([])
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [homelabId])

  // Slugs selected in the UI but not currently reported by the sidecar —
  // typically models that got uninstalled/renamed after the allowlist was
  // last edited. Shown separately so the host can decide to drop or keep them.
  const stranded = useMemo(() => {
    if (!models) return []
    const known = new Set(models.map((m) => m.slug))
    return slugs.filter((s) => !known.has(s))
  }, [models, slugs])

  function toggle(slug: string) {
    setSlugs((xs) => (xs.includes(slug) ? xs.filter((x) => x !== slug) : [...xs, slug]))
  }

  function addDraft() {
    const v = draft.trim()
    if (!v) return
    if (!slugs.includes(v)) setSlugs((xs) => [...xs, v])
    setDraft('')
  }

  function remove(slug: string) {
    setSlugs((xs) => xs.filter((x) => x !== slug))
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

  const loading = models === null && !loadError

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
            Only models you tick will be visible to the consumer using this
            API-Key. Every slug is picked by hand — no "allow all" shortcut.
          </p>

          {loading && (
            <div className="rounded border border-white/10 p-4 text-center text-[12px] text-white/50">
              Loading models from your sidecar…
            </div>
          )}

          {online === false && !loading && (
            <div className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[12px] text-amber-200">
              Sidecar is offline. Showing the current allowlist. You can edit
              slugs by hand, but the authoritative model list will only appear
              once your sidecar reconnects.
            </div>
          )}

          {loadError && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {loadError}
            </div>
          )}

          {online === true && models !== null && models.length === 0 && (
            <div className="rounded border border-dashed border-white/15 p-3 text-center text-[12px] text-white/50">
              Your sidecar reports no models yet. Pull one with
              <code className="mx-1 rounded bg-black/40 px-1 font-mono">ollama pull &lt;model&gt;</code>
              and re-open this dialog.
            </div>
          )}

          {online === true && models !== null && models.length > 0 && (
            <ul className="space-y-1">
              {models.map((m) => {
                const ticked = slugs.includes(m.slug)
                return (
                  <li key={m.slug}>
                    <label className="flex cursor-pointer items-start gap-3 rounded border border-white/8 bg-black/20 p-2 hover:border-white/15">
                      <input
                        type="checkbox"
                        checked={ticked}
                        onChange={() => toggle(m.slug)}
                        className="mt-0.5 h-4 w-4 flex-shrink-0 accent-gold"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <code className="truncate font-mono text-[12px] text-white/90">
                            {m.slug}
                          </code>
                          {m.display_name !== m.slug && (
                            <span className="truncate text-[11px] text-white/50">
                              {m.display_name}
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-white/40">
                          <span>ctx {m.context_length.toLocaleString()}</span>
                          {m.quantisation && <span>{m.quantisation}</span>}
                          {m.capabilities.length > 0 && (
                            <span>{m.capabilities.join(', ')}</span>
                          )}
                        </div>
                      </div>
                    </label>
                  </li>
                )
              })}
            </ul>
          )}

          {stranded.length > 0 && (
            <div>
              <h3 className="mb-2 text-[11px] font-mono uppercase tracking-wider text-amber-300/80">
                Allowed but not on the sidecar right now
              </h3>
              <ul className="space-y-1">
                {stranded.map((s) => (
                  <li
                    key={s}
                    className="flex items-center justify-between rounded border border-amber-500/20 bg-black/20 p-2"
                  >
                    <code className="font-mono text-[12px] text-white/70">{s}</code>
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
            </div>
          )}

          {online === false && (
            <div>
              <h3 className="mb-2 text-[11px] font-mono uppercase tracking-wider text-white/50">
                Add slug manually
              </h3>
              <div className="flex gap-2">
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addDraft()
                    }
                  }}
                  placeholder="llama3.2:8b"
                  className="flex-1 rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-gold/60"
                />
                <button
                  type="button"
                  onClick={addDraft}
                  disabled={!draft.trim()}
                  className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5 disabled:opacity-40"
                >
                  Add
                </button>
              </div>
              {slugs.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {slugs.map((s) => (
                    <li
                      key={s}
                      className="flex items-center justify-between rounded border border-white/8 bg-black/20 p-2"
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
            </div>
          )}

          {error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-white/8 px-5 py-3">
          <div className="text-[11px] text-white/50">
            {slugs.length} model{slugs.length === 1 ? '' : 's'} selected
          </div>
          <div className="flex items-center gap-2">
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
      </div>
    </Sheet>
  )
}
