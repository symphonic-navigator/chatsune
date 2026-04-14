import { useCallback, useEffect, useState } from 'react'
import { webSearchApi } from '../../../core/api/websearch'
import type { WebSearchProvider } from '../../../core/types/websearch'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'

interface ApiKeysTabProps {
  /**
   * Kept on the prop-surface for AppLayout compatibility. Current
   * implementation does not need it — the badge logic lives in
   * UserModal.tsx and reads the same API directly.
   */
  onProvidersLoaded?: () => void
}

interface RowState {
  draft: string
  error: string | null
  busy: 'idle' | 'testing' | 'saving' | 'removing'
  lastTestFeedback: { valid: boolean; error: string | null } | null
}

const EMPTY_ROW: RowState = {
  draft: '',
  error: null,
  busy: 'idle',
  lastTestFeedback: null,
}

export function ApiKeysTab({ onProvidersLoaded }: ApiKeysTabProps) {
  const [providers, setProviders] = useState<WebSearchProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, RowState>>({})

  const refresh = useCallback(async () => {
    setLoadError(null)
    try {
      const list = await webSearchApi.listWebSearchProviders()
      setProviders(list)
      onProvidersLoaded?.()
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Konnte Web-Search-Provider nicht laden.')
    } finally {
      setLoading(false)
    }
  }, [onProvidersLoaded])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const topics = [
      Topics.WEBSEARCH_CREDENTIAL_SET,
      Topics.WEBSEARCH_CREDENTIAL_REMOVED,
      Topics.WEBSEARCH_CREDENTIAL_TESTED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refresh() }))
    return () => unsubs.forEach((u) => u())
  }, [refresh])

  function rowFor(providerId: string): RowState {
    return rows[providerId] ?? EMPTY_ROW
  }

  function patchRow(providerId: string, patch: Partial<RowState>) {
    setRows((prev) => ({
      ...prev,
      [providerId]: { ...(prev[providerId] ?? EMPTY_ROW), ...patch },
    }))
  }

  async function handleTest(provider: WebSearchProvider) {
    const row = rowFor(provider.provider_id)
    if (!row.draft || row.busy !== 'idle') return
    patchRow(provider.provider_id, { busy: 'testing', error: null, lastTestFeedback: null })
    try {
      const res = await webSearchApi.testWebSearchKey(provider.provider_id, row.draft)
      patchRow(provider.provider_id, {
        busy: 'idle',
        lastTestFeedback: { valid: res.valid, error: res.error },
      })
    } catch (err) {
      patchRow(provider.provider_id, {
        busy: 'idle',
        error: err instanceof Error ? err.message : 'Test fehlgeschlagen.',
      })
    }
  }

  async function handleSave(provider: WebSearchProvider) {
    const row = rowFor(provider.provider_id)
    if (!row.draft || row.busy !== 'idle') return
    patchRow(provider.provider_id, { busy: 'saving', error: null })
    try {
      await webSearchApi.setWebSearchKey(provider.provider_id, row.draft)
      // Reset draft; the provider list refetch via the topic subscription
      // will flip is_configured/status on its own.
      patchRow(provider.provider_id, {
        busy: 'idle',
        draft: '',
        lastTestFeedback: null,
      })
      await refresh()
    } catch (err) {
      patchRow(provider.provider_id, {
        busy: 'idle',
        error: err instanceof Error ? err.message : 'Speichern fehlgeschlagen.',
      })
    }
  }

  async function handleRemove(provider: WebSearchProvider) {
    if (!window.confirm(`Schlüssel für ${provider.display_name} wirklich entfernen?`)) return
    patchRow(provider.provider_id, { busy: 'removing', error: null })
    try {
      await webSearchApi.deleteWebSearchKey(provider.provider_id)
      patchRow(provider.provider_id, {
        busy: 'idle',
        draft: '',
        lastTestFeedback: null,
      })
      await refresh()
    } catch (err) {
      patchRow(provider.provider_id, {
        busy: 'idle',
        error: err instanceof Error ? err.message : 'Entfernen fehlgeschlagen.',
      })
    }
  }

  if (loading) {
    return <div className="p-6 text-sm text-white/60">Lade…</div>
  }

  if (loadError) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-red-300">{loadError}</p>
        <button
          type="button"
          onClick={() => { setLoading(true); void refresh() }}
          className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
        >
          Erneut versuchen
        </button>
      </div>
    )
  }

  if (providers.length === 0) {
    return (
      <div className="p-6 text-sm text-white/60">
        Keine Web-Search-Provider registriert.
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      <h3 className="text-lg text-white/90">Web-Search Keys</h3>
      <p className="text-[12px] text-white/50">
        API-Schlüssel für Web-Suchanbieter. LLM-Zugänge werden im Tab „LLM Providers“ gepflegt.
      </p>
      <div className="space-y-3">
        {providers.map((p) => {
          const row = rowFor(p.provider_id)
          const disabled = row.busy !== 'idle'
          return (
            <div
              key={p.provider_id}
              className="rounded border border-white/8 bg-white/5 p-3 space-y-2"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex flex-col">
                  <span className="text-[13px] text-white/85">{p.display_name}</span>
                  <span className="text-[11px] font-mono text-white/35">{p.provider_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  <StatusPill provider={p} />
                  {p.is_configured ? (
                    <span className="rounded bg-green-500/15 px-2 py-0.5 text-[11px] text-green-300 border border-green-500/30">
                      konfiguriert
                    </span>
                  ) : (
                    <span className="text-[11px] text-white/40">–</span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={row.draft}
                  onChange={(e) => patchRow(p.provider_id, {
                    draft: e.target.value,
                    error: null,
                    lastTestFeedback: null,
                  })}
                  placeholder={p.is_configured ? '•••  (unverändert lassen)' : ''}
                  disabled={disabled}
                  className="flex-1 rounded bg-white/5 border border-white/10 px-3 py-1.5 text-[13px] text-white/85 placeholder:text-white/30 outline-none focus:border-white/25 disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => handleTest(p)}
                  disabled={disabled || row.draft.length === 0}
                  className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {row.busy === 'testing' ? 'Teste…' : 'Test'}
                </button>
                <button
                  type="button"
                  onClick={() => handleSave(p)}
                  disabled={disabled || row.draft.length === 0}
                  className="rounded bg-purple/70 px-3 py-1 text-[12px] text-white hover:bg-purple/80 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {row.busy === 'saving' ? 'Speichere…' : 'Speichern'}
                </button>
                {p.is_configured && (
                  <button
                    type="button"
                    onClick={() => handleRemove(p)}
                    disabled={disabled}
                    className="rounded border border-red-500/30 px-3 py-1 text-[12px] text-red-300 hover:bg-red-500/10 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {row.busy === 'removing' ? 'Entferne…' : 'Entfernen'}
                  </button>
                )}
              </div>

              {row.lastTestFeedback && (
                <div
                  className={`text-[12px] ${row.lastTestFeedback.valid ? 'text-green-300' : 'text-red-300'}`}
                >
                  {row.lastTestFeedback.valid
                    ? 'Schlüssel ist gültig.'
                    : row.lastTestFeedback.error ?? 'Test fehlgeschlagen.'}
                </div>
              )}
              {row.error && (
                <div className="text-[12px] text-red-300">{row.error}</div>
              )}
              {p.last_test_status === 'failed' && p.last_test_error && !row.lastTestFeedback && (
                <div className="text-[12px] text-red-300/80">
                  Letzter Test fehlgeschlagen: {p.last_test_error}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StatusPill({ provider }: { provider: WebSearchProvider }) {
  if (provider.last_test_status === 'valid') {
    return (
      <span className="rounded bg-green-500/15 px-2 py-0.5 text-[11px] text-green-300 border border-green-500/30">
        valid
      </span>
    )
  }
  if (provider.last_test_status === 'failed') {
    return (
      <span className="rounded bg-red-500/15 px-2 py-0.5 text-[11px] text-red-300 border border-red-500/30">
        failed
      </span>
    )
  }
  if (provider.last_test_status === 'untested') {
    return (
      <span className="rounded bg-white/5 px-2 py-0.5 text-[11px] text-white/50 border border-white/10">
        untested
      </span>
    )
  }
  return null
}
