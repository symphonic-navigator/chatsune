import { useEffect, useState } from 'react'
import { Sheet } from '../../core/components/Sheet'
import { ApiError } from '../../core/api/client'
import { homelabsApi } from './api'
import { HostKeyRevealModal } from './HostKeyRevealModal'

/**
 * Two-step modal: collect display name + self-access slug + concurrency
 * → POST → swap to the one-shot `HostKeyRevealModal`. The reveal modal
 * re-uses the same `onClose` so dismissing it also closes the create flow,
 * preserving the expected "one modal at a time" mental model without
 * requiring modal stacking.
 */

const SLUG_FALLBACK = 'my-homelab'

/** Deterministic slugify: lowercase, non-alnum → `-`, collapse, trim. */
function slugify(input: string): string {
  const lowered = input.toLowerCase()
  const hyphenated = lowered.replace(/[^a-z0-9]+/g, '-')
  const collapsed = hyphenated.replace(/-+/g, '-')
  const trimmed = collapsed.replace(/^-+/, '').replace(/-+$/, '')
  return trimmed.length > 0 ? trimmed.slice(0, 63) : SLUG_FALLBACK
}

function isSlugValid(slug: string): boolean {
  if (slug.length < 1 || slug.length > 63) return false
  return /^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)
}

function isSlugExistsBody(
  body: unknown,
): body is { detail: { error: string; suggested_slug: string } } {
  if (typeof body !== 'object' || body === null) return false
  const detail = (body as Record<string, unknown>).detail
  if (typeof detail !== 'object' || detail === null) return false
  const d = detail as Record<string, unknown>
  return d.error === 'slug_exists' && typeof d.suggested_slug === 'string'
}

export function HomelabCreateModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [maxConcurrent, setMaxConcurrent] = useState<number>(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [suggestedSlug, setSuggestedSlug] = useState<string | null>(null)
  const [revealKey, setRevealKey] = useState<string | null>(null)

  // Auto-suggest the slug from the display name until the user edits it
  // manually. Once they touch it, we stop overriding their input.
  useEffect(() => {
    if (slugTouched) return
    setSlug(slugify(name))
  }, [name, slugTouched])

  const trimmedName = name.trim()
  const trimmedSlug = slug.trim()
  const slugInvalid = trimmedSlug.length > 0 && !isSlugValid(trimmedSlug)
  const concurrencyInvalid =
    !Number.isInteger(maxConcurrent) || maxConcurrent < 1 || maxConcurrent > 64
  const canSubmit =
    !busy &&
    trimmedName.length > 0 &&
    trimmedSlug.length > 0 &&
    !slugInvalid &&
    !concurrencyInvalid

  async function submit() {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    setSuggestedSlug(null)
    try {
      const res = await homelabsApi.create({
        display_name: trimmedName,
        host_slug: trimmedSlug,
        max_concurrent_requests: maxConcurrent,
      })
      setRevealKey(res.plaintext_host_key)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && isSlugExistsBody({ detail: err.body })) {
        const suggested = (err.body as { error: string; suggested_slug: string }).suggested_slug
        setSuggestedSlug(suggested)
        setError(`Slug "${trimmedSlug}" is already in use.`)
      } else if (err instanceof ApiError && typeof err.body === 'object' && err.body !== null) {
        const body = err.body as { detail?: unknown }
        if (typeof body.detail === 'object' && body.detail !== null) {
          const d = body.detail as { error?: unknown; suggested_slug?: unknown }
          if (d.error === 'slug_exists' && typeof d.suggested_slug === 'string') {
            setSuggestedSlug(d.suggested_slug)
            setError(`Slug "${trimmedSlug}" is already in use.`)
          } else {
            setError(err.message || 'Create failed.')
          }
        } else {
          setError(err.message || 'Create failed.')
        }
      } else {
        setError(err instanceof Error ? err.message : 'Create failed.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (revealKey) {
    return <HostKeyRevealModal plaintext={revealKey} onClose={onClose} />
  }

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="md"
      ariaLabel="Create homelab"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            Create homelab
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
            Give it a name you'll recognise in the sidebar and in your
            sidecar's logs.
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
                if (e.key === 'Enter' && canSubmit) void submit()
              }}
              maxLength={80}
              placeholder="e.g. Wohnzimmer-GPU"
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-gold/60"
            />
          </div>
          <div className="space-y-1">
            <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
              Self-access slug
            </label>
            <input
              type="text"
              value={slug}
              onChange={(e) => {
                setSlugTouched(true)
                setSlug(e.target.value)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canSubmit) void submit()
              }}
              maxLength={63}
              placeholder="my-homelab"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-gold/60"
            />
            {slugInvalid && (
              <p className="text-[11px] text-amber-300">
                Slug must be lowercase letters, numbers, and hyphens (1–63 chars).
              </p>
            )}
            <p className="text-[11px] text-white/50">
              A slug you'll recognise in your LLM providers list — this is how
              you'll use your own homelab without needing an API-Key.
            </p>
          </div>
          <div className="space-y-1">
            <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
              Max parallel requests
            </label>
            <input
              type="number"
              min={1}
              max={64}
              value={maxConcurrent}
              onChange={(e) => setMaxConcurrent(Number(e.target.value))}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canSubmit) void submit()
              }}
              className="w-28 rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-gold/60"
            />
            <p className="text-[11px] text-white/50">
              Total simultaneous requests across ALL users of this homelab.
            </p>
          </div>
          {error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              <p>{error}</p>
              {suggestedSlug && (
                <button
                  type="button"
                  onClick={() => {
                    setSlug(suggestedSlug)
                    setSlugTouched(true)
                    setSuggestedSlug(null)
                    setError(null)
                  }}
                  className="mt-1.5 rounded border border-red-400/40 px-2 py-0.5 text-[11px] text-red-200 hover:bg-red-500/15"
                >
                  Use suggested slug "{suggestedSlug}"
                </button>
              )}
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
            {busy ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
