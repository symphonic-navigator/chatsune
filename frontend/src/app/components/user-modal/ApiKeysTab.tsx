import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { llmApi } from '../../../core/api/llm'
import type { ProviderCredentialDto } from '../../../core/types/llm'

type TestStatus = 'untested' | 'valid' | 'failed' | 'testing'

interface KeyState {
  provider: ProviderCredentialDto
  editing: boolean
  editValue: string
  localTestStatus: TestStatus | null
  localTestError: string | null
  saving: boolean
  confirmDelete: boolean
}

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  valid:    { label: 'VERIFIED',   className: 'bg-green-400/8 text-green-400 border-green-400/20' },
  failed:   { label: 'FAILED',    className: 'bg-red-400/10 text-red-400 border-red-400/20' },
  untested: { label: 'UNTESTED',  className: 'bg-white/6 text-white/40 border-white/10' },
  testing:  { label: 'TESTING...', className: 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20' },
}

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_GOLD = `${BTN} border-gold/30 text-gold hover:bg-gold/10 hover:border-gold/40`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

export function ApiKeysTab({ onProvidersLoaded }: { onProvidersLoaded?: (providers: ProviderCredentialDto[]) => void }) {
  const [keys, setKeys] = useState<KeyState[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const deleteTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const announceId = useId()
  const configuredCount = useMemo(() => keys.filter((k) => k.provider.is_configured).length, [keys])
  const anyConfirming = useMemo(() => keys.some((k) => k.confirmDelete), [keys])

  const fetchProviders = useCallback(async () => {
    try {
      const providers = await llmApi.listProviders()
      setKeys(providers.map((p) => ({
        provider: p,
        editing: false,
        editValue: '',
        localTestStatus: null,
        localTestError: null,
        saving: false,
        confirmDelete: false,
      })))
      onProvidersLoaded?.(providers)
      setError(null)
    } catch {
      setError('Could not load providers. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [onProvidersLoaded])

  useEffect(() => {
    fetchProviders()
    return () => {
      Object.values(deleteTimers.current).forEach(clearTimeout)
    }
  }, [fetchProviders])

  function updateKey(providerId: string, patch: Partial<KeyState>) {
    setKeys((prev) => prev.map((k) =>
      k.provider.provider_id === providerId ? { ...k, ...patch } : k
    ))
  }

  function startEdit(providerId: string) {
    updateKey(providerId, { editing: true, editValue: '' })
  }

  function cancelEdit(providerId: string) {
    updateKey(providerId, { editing: false, editValue: '', saving: false })
  }

  async function handleSave(providerId: string, apiKey: string) {
    updateKey(providerId, { saving: true })
    try {
      await llmApi.setKey(providerId, { api_key: apiKey })
      updateKey(providerId, { editing: false, editValue: '', saving: false, localTestStatus: 'testing', localTestError: null })
      // Update is_configured immediately
      setKeys((prev) => prev.map((k) =>
        k.provider.provider_id === providerId
          ? { ...k, provider: { ...k.provider, is_configured: true, test_status: 'untested', last_test_error: null } }
          : k
      ))
      // Auto-test
      try {
        const result = await llmApi.testStoredKey(providerId)
        const status = result.valid ? 'valid' : 'failed'
        updateKey(providerId, { localTestStatus: status, localTestError: result.error })
        setKeys((prev) => prev.map((k) =>
          k.provider.provider_id === providerId
            ? { ...k, provider: { ...k.provider, test_status: status, last_test_error: result.error } }
            : k
        ))
        // Re-fetch to get authoritative state
        const providers = await llmApi.listProviders()
        setKeys((prev) => prev.map((k) => {
          const fresh = providers.find((p) => p.provider_id === k.provider.provider_id)
          return fresh ? { ...k, provider: fresh, localTestStatus: null, localTestError: null } : k
        }))
        onProvidersLoaded?.(providers)
      } catch {
        updateKey(providerId, { localTestStatus: 'failed', localTestError: 'Test request failed' })
      }
    } catch {
      updateKey(providerId, { saving: false })
      setError('Could not save API key. Please try again.')
    }
  }

  async function handleTest(providerId: string) {
    updateKey(providerId, { localTestStatus: 'testing', localTestError: null })
    try {
      const result = await llmApi.testStoredKey(providerId)
      const status = result.valid ? 'valid' : 'failed'
      updateKey(providerId, { localTestStatus: status, localTestError: result.error })
      setKeys((prev) => prev.map((k) =>
        k.provider.provider_id === providerId
          ? { ...k, provider: { ...k.provider, test_status: status, last_test_error: result.error } }
          : k
      ))
      const providers = await llmApi.listProviders()
      setKeys((prev) => prev.map((k) => {
        const fresh = providers.find((p) => p.provider_id === k.provider.provider_id)
        return fresh ? { ...k, provider: fresh, localTestStatus: null, localTestError: null } : k
      }))
      onProvidersLoaded?.(providers)
    } catch {
      updateKey(providerId, { localTestStatus: 'failed', localTestError: 'Test request failed' })
    }
  }

  async function handleDelete(providerId: string) {
    try {
      await llmApi.removeKey(providerId)
      setKeys((prev) => prev.map((k) =>
        k.provider.provider_id === providerId
          ? {
              ...k,
              provider: { ...k.provider, is_configured: false, test_status: null, last_test_error: null, created_at: null },
              confirmDelete: false,
              editing: false,
              localTestStatus: null,
              localTestError: null,
            }
          : k
      ))
      const providers = await llmApi.listProviders()
      onProvidersLoaded?.(providers)
    } catch {
      setError('Could not delete API key. Please try again.')
    }
  }

  function startDeleteConfirm(providerId: string) {
    if (deleteTimers.current[providerId]) clearTimeout(deleteTimers.current[providerId])
    updateKey(providerId, { confirmDelete: true })
    deleteTimers.current[providerId] = setTimeout(() => {
      updateKey(providerId, { confirmDelete: false })
    }, 3000)
  }

  function getDisplayStatus(k: KeyState): TestStatus | null {
    if (k.localTestStatus) return k.localTestStatus
    if (!k.provider.is_configured) return null
    return (k.provider.test_status as TestStatus) ?? 'untested'
  }

  function getDisplayError(k: KeyState): string | null {
    if (k.localTestError !== null) return k.localTestError
    return k.provider.last_test_error
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
      </div>
    )
  }

  if (error && keys.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-20">
        <p className="text-[12px] text-red-400">{error}</p>
        <button type="button" onClick={fetchProviders} className={BTN_GOLD}>Retry</button>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div id={announceId} role="status" aria-live="polite" className="sr-only">
        {anyConfirming ? 'Confirm delete: press the SURE? button again to remove this key.' : ''}
      </div>
      {error && (
        <div role="alert" className="mx-4 mt-3 rounded-lg border border-red-400/20 bg-red-400/5 px-4 py-2 text-[11px] text-red-400">
          {error}
        </div>
      )}

      {configuredCount === 0 && (
        <div className="mx-4 mt-4 rounded-lg border border-gold/20 bg-gold/5 px-4 py-4 flex flex-col gap-2">
          <p className="text-[12px] font-mono text-gold/90 uppercase tracking-wider">Add your first API key</p>
          <p className="text-[11px] text-white/60 leading-relaxed">
            Without an API key Chatsune cannot reach any LLM provider. Pick a provider below and click SET to add one.
          </p>
        </div>
      )}

      <div className="px-4 pt-3">
        <div className="grid grid-cols-[1fr_1fr_6rem_6rem] gap-2 border-b border-white/6 px-3 py-2">
          <span className="text-[10px] uppercase tracking-wider text-white/60 font-mono">Provider</span>
          <span className="text-[10px] uppercase tracking-wider text-white/60 font-mono">Key</span>
          <span className="text-[10px] uppercase tracking-wider text-white/60 font-mono">Status</span>
          <span className="text-[10px] uppercase tracking-wider text-white/60 font-mono text-right">Ops</span>
        </div>

        {keys.map((k) => {
          const status = getDisplayStatus(k)
          const errorMsg = getDisplayError(k)
          const isFailed = status === 'failed'

          return (
            <div key={k.provider.provider_id}>
              <div
                className={[
                  'grid grid-cols-[1fr_1fr_6rem_6rem] gap-2 items-center px-3 py-2.5 border-b border-white/6 transition-colors group',
                  isFailed ? 'bg-red-400/[0.03]' : 'hover:bg-white/4',
                ].join(' ')}
              >
                <span className={`text-[12px] font-mono ${k.provider.is_configured ? 'text-white/80' : 'text-white/40'}`}>
                  {k.provider.display_name}
                </span>

                <span className={`text-[12px] font-mono ${k.provider.is_configured ? 'text-white/60 tracking-[2px]' : 'text-white/60 italic'}`} aria-label={k.provider.is_configured ? 'API key set' : 'No API key configured'}>
                  {k.provider.is_configured ? '••••••••••••' : 'not configured'}
                </span>

                <div>
                  {status && STATUS_BADGE[status] ? (
                    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] uppercase tracking-wider border font-mono ${STATUS_BADGE[status].className}`}>
                      {status === 'testing' && (
                        <span className="inline-block h-2 w-2 animate-spin rounded-full border border-yellow-400/30 border-t-yellow-400" />
                      )}
                      {STATUS_BADGE[status].label}
                    </span>
                  ) : (
                    <span className="text-[11px] text-white/15">—</span>
                  )}
                </div>

                <div className="flex gap-1 justify-end">
                  {k.provider.is_configured ? (
                    <>
                      <button type="button" onClick={() => startEdit(k.provider.provider_id)} aria-label={`Edit API key for ${k.provider.display_name}`} title="Edit API key" className={BTN_NEUTRAL}>
                        EDIT
                      </button>
                      <button
                        type="button"
                        onClick={() => handleTest(k.provider.provider_id)}
                        disabled={status === 'testing'}
                        aria-label={`Test API key for ${k.provider.display_name}`}
                        title="Test connectivity"
                        className={`${BTN_NEUTRAL} ${status === 'testing' ? 'opacity-30 cursor-not-allowed' : ''}`}
                      >
                        TEST
                      </button>
                      {k.confirmDelete ? (
                        <button type="button" onClick={() => handleDelete(k.provider.provider_id)} aria-label={`Confirm delete API key for ${k.provider.display_name}`} title="Confirm delete" className={BTN_RED}>
                          SURE?
                        </button>
                      ) : (
                        <button type="button" onClick={() => startDeleteConfirm(k.provider.provider_id)} aria-label={`Delete API key for ${k.provider.display_name}`} title="Delete API key" className={BTN_NEUTRAL}>
                          DEL
                        </button>
                      )}
                    </>
                  ) : (
                    <button type="button" onClick={() => startEdit(k.provider.provider_id)} aria-label={`Set API key for ${k.provider.display_name}`} title="Set API key" className={BTN_GOLD}>
                      SET
                    </button>
                  )}
                </div>
              </div>

              {k.editing && (
                <EditRow
                  editValue={k.editValue}
                  saving={k.saving}
                  errorMessage={isFailed ? errorMsg : null}
                  onChangeValue={(v) => updateKey(k.provider.provider_id, { editValue: v })}
                  onSave={() => handleSave(k.provider.provider_id, k.editValue)}
                  onCancel={() => cancelEdit(k.provider.provider_id)}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function EditRow({
  editValue,
  saving,
  errorMessage,
  onChangeValue,
  onSave,
  onCancel,
}: {
  editValue: string
  saving: boolean
  errorMessage: string | null
  onChangeValue: (v: string) => void
  onSave: () => void
  onCancel: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const inputId = useId()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && editValue.trim()) onSave()
    if (e.key === 'Escape') onCancel()
  }

  return (
    <div className="px-3 py-3 bg-white/[0.02] border-b border-white/6">
      {errorMessage && (
        <p className="text-[10px] text-red-400 mb-2 font-mono">{errorMessage}</p>
      )}
      <div className="flex gap-2 items-center">
        <div className="relative flex-1">
          <label htmlFor={inputId} className="sr-only">API key</label>
          <input
            id={inputId}
            ref={inputRef}
            type={visible ? 'text' : 'password'}
            value={editValue}
            onChange={(e) => onChangeValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Paste your API key..."
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 pr-8 text-[12px] font-mono text-white/75 placeholder-white/30 outline-none focus:border-gold/30 transition-colors"
          />
          <button
            type="button"
            onClick={() => setVisible(!visible)}
            aria-label={visible ? 'Hide API key' : 'Show API key'}
            aria-pressed={visible}
            title={visible ? 'Hide' : 'Show'}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-white/60 hover:text-white/80 transition-colors"
            tabIndex={-1}
          >
            {visible ? '◉' : '○'}
          </button>
        </div>
        <button
          type="button"
          onClick={onSave}
          disabled={!editValue.trim() || saving}
          className={`${BTN_GOLD} ${(!editValue.trim() || saving) ? 'opacity-30 cursor-not-allowed' : ''}`}
        >
          {saving ? 'SAVING...' : 'SAVE'}
        </button>
        <button type="button" onClick={onCancel} className={BTN_NEUTRAL}>
          CANCEL
        </button>
      </div>
      <p className="mt-1.5 text-[9px] text-white/60 font-mono">Saving will automatically run a connectivity test</p>
    </div>
  )
}
