import { useEffect, useMemo, useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'
import { llmApi } from '../../../core/api/llm'
import { resolveAdapterView } from '../../../core/adapters/AdapterViewRegistry'
import { ApiError } from '../../../core/api/client'
import type { Adapter, Connection } from '../../../core/types/llm'

export interface NewConnectionPreset {
  adapter_type: string
  display_name: string
  slug: string
  config: Record<string, unknown>
}

interface ConnectionConfigModalProps {
  /** Existing connection in edit mode. */
  connection?: Connection
  /** Pre-filled preset when creating a new connection from the wizard. */
  newConnectionPreset?: NewConnectionPreset
  onClose: () => void
  onSaved: () => void | Promise<void>
  onDeleted?: () => void | Promise<void>
}

function isSlugErrorBody(body: unknown): body is { detail: { error: string; suggested_slug: string } } {
  if (typeof body !== 'object' || body === null) return false
  const detail = (body as Record<string, unknown>).detail
  if (typeof detail !== 'object' || detail === null) return false
  const d = detail as Record<string, unknown>
  return d.error === 'slug_exists' && typeof d.suggested_slug === 'string'
}

/**
 * Builds the placeholder Connection passed into the adapter view in
 * "new" mode. The empty id signals "not yet persisted" — adapter views
 * use it to disable id-bound buttons (Test, Diagnostics).
 */
function placeholderFromPreset(preset: NewConnectionPreset): Connection {
  const now = new Date().toISOString()
  return {
    id: '',
    user_id: '',
    adapter_type: preset.adapter_type,
    display_name: preset.display_name,
    slug: preset.slug,
    config: preset.config,
    last_test_status: null,
    last_test_error: null,
    last_test_at: null,
    created_at: now,
    updated_at: now,
  }
}

export function ConnectionConfigModal({
  connection,
  newConnectionPreset,
  onClose,
  onSaved,
  onDeleted,
}: ConnectionConfigModalProps) {
  const isNew = connection === undefined
  const initial: Connection = useMemo(
    () => connection ?? placeholderFromPreset(newConnectionPreset!),
    [connection, newConnectionPreset],
  )

  const [displayName, setDisplayName] = useState(initial.display_name)
  const [slug, setSlug] = useState(initial.slug)
  const [config, setConfig] = useState<Record<string, unknown>>(initial.config)

  const [adapter, setAdapter] = useState<Adapter | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [suggestedSlug, setSuggestedSlug] = useState<string | null>(null)

  // Working copy of the Connection passed to the adapter view. We rebuild it
  // whenever fields the view cares about change so it reflects the latest
  // state — important so the URL-collision warning re-evaluates live.
  const workingConnection: Connection = useMemo(
    () => ({ ...initial, display_name: displayName, slug, config }),
    [initial, displayName, slug, config],
  )

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const all = await llmApi.listAdapters()
        if (cancelled) return
        setAdapter(all.find((a) => a.adapter_type === initial.adapter_type) ?? null)
      } catch {
        if (!cancelled) setAdapter(null)
      }
    })()
    return () => { cancelled = true }
  }, [initial.adapter_type])

  async function handleSave() {
    const trimmedName = displayName.trim()
    const trimmedSlug = slug.trim()
    if (!trimmedName || !trimmedSlug) {
      setError('Bitte Anzeigename und Slug ausfüllen.')
      return
    }
    setSaving(true)
    setError(null)
    setSuggestedSlug(null)
    try {
      if (isNew) {
        await llmApi.createConnection({
          adapter_type: initial.adapter_type,
          display_name: trimmedName,
          slug: trimmedSlug,
          config,
        })
      } else {
        await llmApi.updateConnection(connection!.id, {
          display_name: trimmedName !== connection!.display_name ? trimmedName : undefined,
          slug: trimmedSlug !== connection!.slug ? trimmedSlug : undefined,
          config,
        })
      }
      await onSaved()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && isSlugErrorBody({ detail: err.body })) {
        const suggested = (err.body as { error: string; suggested_slug: string }).suggested_slug
        setSuggestedSlug(suggested)
        setError(`Slug "${trimmedSlug}" ist bereits vergeben.`)
      } else if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as { detail?: unknown }
        if (typeof body.detail === 'object' && body.detail !== null) {
          const d = body.detail as { error?: unknown; suggested_slug?: unknown }
          if (d.error === 'slug_exists' && typeof d.suggested_slug === 'string') {
            setSuggestedSlug(d.suggested_slug)
            setError(`Slug "${trimmedSlug}" ist bereits vergeben.`)
          } else {
            setError(err.message || 'Speichern fehlgeschlagen.')
          }
        } else {
          setError(err.message || 'Speichern fehlgeschlagen.')
        }
      } else {
        setError(err instanceof Error ? err.message : 'Speichern fehlgeschlagen.')
      }
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (isNew) return
    if (!confirmDelete) {
      setConfirmDelete(true)
      window.setTimeout(() => setConfirmDelete(false), 3000)
      return
    }
    setDeleting(true)
    try {
      await llmApi.deleteConnection(connection!.id)
      if (onDeleted) await onDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Löschen fehlgeschlagen.')
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  const AdapterView = adapter ? resolveAdapterView(adapter.view_id) : null

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="xl"
      ariaLabel={isNew ? 'Neue Verbindung' : 'Verbindung bearbeiten'}
      className="border border-white/8 bg-elevated"
    >
      <div className="flex max-h-full flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            {isNew ? 'Neue Verbindung' : 'Verbindung bearbeiten'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Schließen"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Generic frame: display name + slug */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
                Anzeigename
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
              />
            </div>
            <div className="space-y-1">
              <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
                Slug
              </label>
              <input
                type="text"
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-purple/60"
              />
            </div>
          </div>

          {/* Adapter type label */}
          <div className="text-[11px] text-white/40">
            Adapter: <span className="font-mono text-white/60">{initial.adapter_type}</span>
          </div>

          {/* Adapter-specific view */}
          {AdapterView ? (
            <div className="rounded border border-white/8 p-4">
              <AdapterView
                connection={workingConnection}
                onConfigChange={setConfig}
                onDisplayNameChange={setDisplayName}
                onSlugChange={setSlug}
              />
            </div>
          ) : (
            <div className="rounded border border-white/8 p-4 text-sm text-white/50">
              Keine Konfigurationsansicht für Adapter "{initial.adapter_type}" registriert.
            </div>
          )}

          {/* Errors */}
          {error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              <p>{error}</p>
              {suggestedSlug && (
                <button
                  type="button"
                  onClick={() => {
                    setSlug(suggestedSlug)
                    setSuggestedSlug(null)
                    setError(null)
                  }}
                  className="mt-1.5 rounded border border-red-400/40 px-2 py-0.5 text-[11px] text-red-200 hover:bg-red-500/15"
                >
                  Slug "{suggestedSlug}" vorschlagen — übernehmen?
                </button>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/6 px-5 py-3">
          <div>
            {!isNew && onDeleted && (
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className={[
                  'rounded border px-3 py-1 text-[12px]',
                  confirmDelete
                    ? 'border-red-500/50 bg-red-500/15 text-red-200'
                    : 'border-white/15 text-white/70 hover:bg-white/5',
                  deleting ? 'opacity-40 cursor-not-allowed' : '',
                ].join(' ')}
              >
                {deleting
                  ? 'Lösche…'
                  : confirmDelete
                    ? 'Wirklich löschen?'
                    : 'Löschen'}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/70 hover:bg-white/5"
            >
              Abbrechen
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded bg-purple/70 px-3 py-1 text-[12px] text-white hover:bg-purple/80 disabled:opacity-40"
            >
              {saving ? 'Speichere…' : 'Speichern'}
            </button>
          </div>
        </div>
      </div>
    </Sheet>
  )
}
