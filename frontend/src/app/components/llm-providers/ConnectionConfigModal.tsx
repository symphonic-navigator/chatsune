import { useEffect, useMemo, useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'
import { llmApi } from '../../../core/api/llm'
import { resolveAdapterView } from '../../../core/adapters/AdapterViewRegistry'
import { ApiError } from '../../../core/api/client'
import type { Adapter, Connection, TestResultResponse } from '../../../core/types/llm'

export interface NewConnectionPreset {
  adapter_type: string
  display_name: string
  slug: string
  config: Record<string, unknown>
  /** Fields that must be non-empty — forwarded from the template. */
  required_config_fields: string[]
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

function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim().length === 0
  return false
}

export function ConnectionConfigModal({
  connection: connectionProp,
  newConnectionPreset,
  onClose,
  onSaved,
  onDeleted,
}: ConnectionConfigModalProps) {
  const isNew = connectionProp === undefined
  const initial: Connection = useMemo(
    () => connectionProp ?? placeholderFromPreset(newConnectionPreset!),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  // Required-field list is only enforced in new mode. In edit mode the
  // user may legitimately update individual config parts without
  // re-supplying a field that was saved under a prior policy.
  const requiredConfigFields = useMemo(
    () => (isNew ? (newConnectionPreset?.required_config_fields ?? []) : []),
    [isNew, newConnectionPreset],
  )

  const [displayName, setDisplayName] = useState(initial.display_name)
  const [slug, setSlug] = useState(initial.slug)
  const [config, setConfig] = useState<Record<string, unknown>>(initial.config)

  // Local copy of the persisted connection — refreshed after every save so
  // adapter views (e.g. OllamaHttpView's apiKeyState) re-evaluate immediately.
  const [connection, setConnection] = useState<Connection>(initial)

  const [adapter, setAdapter] = useState<Adapter | null>(null)
  const [saving, setSaving] = useState(false)
  const [closeAfter, setCloseAfter] = useState(false)
  const [testResult, setTestResult] = useState<TestResultResponse | null>(null)
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [suggestedSlug, setSuggestedSlug] = useState<string | null>(null)

  // Working copy of the Connection passed to the adapter view. We rebuild it
  // whenever fields the view cares about change so it reflects the latest
  // state — important so the URL-collision warning re-evaluates live.
  // After a save we also want the refreshed connection (with updated config /
  // api_key SecretFieldView) to propagate, so we spread `connection` as the base.
  const workingConnection: Connection = useMemo(
    () => ({ ...connection, display_name: displayName, slug, config }),
    [connection, displayName, slug, config],
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

  const missingRequired = useMemo(
    () => requiredConfigFields.filter((name) => isEmptyValue(config[name])),
    [requiredConfigFields, config],
  )

  function validateLocally(): string[] {
    const errors: string[] = []
    if (!displayName.trim()) errors.push('Display name is required.')
    if (!slug.trim()) errors.push('Slug is required.')
    if (missingRequired.length > 0) {
      const label = missingRequired[0] === 'api_key' ? 'API key' : missingRequired[0]
      errors.push(`${label} is required for this template.`)
    }
    return errors
  }

  async function handleSave({ closeAfter: shouldClose }: { closeAfter: boolean }) {
    const errors = validateLocally()
    if (errors.length > 0) {
      setValidationErrors(errors)
      return
    }
    setValidationErrors([])
    setSaving(true)
    setCloseAfter(shouldClose)
    setTestResult(null)
    setErrorMessage(null)
    setSuggestedSlug(null)

    try {
      const trimmedName = displayName.trim()
      const trimmedSlug = slug.trim()

      const saved = isNew
        ? await llmApi.createConnection({
            adapter_type: initial.adapter_type,
            display_name: trimmedName,
            slug: trimmedSlug,
            config,
          })
        : await llmApi.updateConnection(connection.id, {
            display_name: trimmedName !== connection.display_name ? trimmedName : undefined,
            slug: trimmedSlug !== connection.slug ? trimmedSlug : undefined,
            config,
          })

      // Refresh local connection state — this is what flips apiKeyState.is_set
      // from false to true so the placeholder updates to "leave empty to keep".
      setConnection(saved)

      const result = await llmApi.testConnection(saved.id)
      setTestResult(result)

      // Notify parent so it can refresh the connection list.
      await onSaved()

      if (shouldClose) {
        onClose()
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && isSlugErrorBody({ detail: err.body })) {
        const suggested = (err.body as { error: string; suggested_slug: string }).suggested_slug
        setSuggestedSlug(suggested)
        setErrorMessage(`Slug "${slug.trim()}" is already in use.`)
      } else if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as { detail?: unknown }
        if (typeof body.detail === 'object' && body.detail !== null) {
          const d = body.detail as { error?: unknown; suggested_slug?: unknown }
          if (d.error === 'slug_exists' && typeof d.suggested_slug === 'string') {
            setSuggestedSlug(d.suggested_slug as string)
            setErrorMessage(`Slug "${slug.trim()}" is already in use.`)
          } else {
            setErrorMessage(err.message || 'Save failed.')
          }
        } else {
          setErrorMessage(err.message || 'Save failed.')
        }
      } else {
        setErrorMessage(err instanceof Error ? err.message : 'Save failed.')
      }
    } finally {
      setSaving(false)
      setCloseAfter(false)
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
      await llmApi.deleteConnection(connection.id)
      if (onDeleted) await onDeleted()
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Delete failed.')
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
      ariaLabel={isNew ? 'New connection' : 'Edit connection'}
      className="border border-white/8 bg-elevated"
    >
      <div className="flex max-h-full flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            {isNew ? 'New connection' : 'Edit connection'}
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

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Generic frame: display name + slug */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
                Display name
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
                requiredConfigFields={requiredConfigFields}
                onConfigChange={setConfig}
                onDisplayNameChange={setDisplayName}
                onSlugChange={setSlug}
              />
            </div>
          ) : (
            <div className="rounded border border-white/8 p-4 text-sm text-white/50">
              No configuration view registered for adapter "{initial.adapter_type}".
            </div>
          )}

          {/* Test result pill */}
          {testResult && (
            <div
              className={[
                'rounded border px-3 py-2 text-[12px]',
                testResult.valid
                  ? 'border-green-500/30 bg-green-500/10 text-green-300'
                  : 'border-red-500/30 bg-red-500/10 text-red-300',
              ].join(' ')}
            >
              {testResult.valid ? 'Connection OK.' : `Error: ${testResult.error ?? 'unknown'}`}
            </div>
          )}

          {/* Validation errors */}
          {validationErrors.length > 0 && (
            <div className="space-y-1">
              {validationErrors.map((msg, i) => (
                <div
                  key={i}
                  className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300"
                >
                  {msg}
                </div>
              ))}
            </div>
          )}

          {/* General error / slug collision */}
          {errorMessage && (
            <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              <p>{errorMessage}</p>
              {suggestedSlug && (
                <button
                  type="button"
                  onClick={() => {
                    setSlug(suggestedSlug)
                    setSuggestedSlug(null)
                    setErrorMessage(null)
                  }}
                  className="mt-1.5 rounded border border-red-400/40 px-2 py-0.5 text-[11px] text-red-200 hover:bg-red-500/15"
                >
                  Use suggested slug "{suggestedSlug}"
                </button>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/8 px-5 py-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="text-[12px] text-white/60 hover:text-white/80"
            >
              Cancel
            </button>
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
                  ? 'Deleting…'
                  : confirmDelete
                    ? 'Delete this connection?'
                    : 'Delete'}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSave({ closeAfter: false })}
              disabled={saving}
              className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5 disabled:opacity-40"
            >
              {saving && !closeAfter ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => void handleSave({ closeAfter: true })}
              disabled={saving}
              className="rounded bg-gold/90 px-4 py-1.5 text-[12px] font-semibold text-black hover:bg-gold disabled:opacity-40"
            >
              {saving && closeAfter ? 'Saving…' : 'Save and close'}
            </button>
          </div>
        </div>
      </div>
    </Sheet>
  )
}
