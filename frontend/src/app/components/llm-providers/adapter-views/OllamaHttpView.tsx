import { useEffect, useId, useState } from 'react'
import type { AdapterViewProps } from '../../../../core/adapters/AdapterViewRegistry'
import { llmApi } from '../../../../core/api/llm'
import type { Connection, SecretFieldView } from '../../../../core/types/llm'

interface DiagnosticsState {
  loading: boolean
  data: { ps: unknown; tags: unknown } | null
  error: string | null
}

interface TestState {
  loading: boolean
  result: { valid: boolean; error: string | null } | null
}

function isSecretFieldView(value: unknown): value is SecretFieldView {
  return (
    typeof value === 'object' &&
    value !== null &&
    'is_set' in (value as Record<string, unknown>) &&
    typeof (value as SecretFieldView).is_set === 'boolean'
  )
}

function normaliseUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, '').toLowerCase()
}

export function OllamaHttpView({ connection, onConfigChange }: AdapterViewProps) {
  const urlId = useId()
  const keyId = useId()
  const parId = useId()

  const cfg = connection.config
  const initialUrl = typeof cfg.url === 'string' ? cfg.url : ''
  const initialMaxParallel =
    typeof cfg.max_parallel === 'number'
      ? cfg.max_parallel
      : Number(cfg.max_parallel) || 1
  const apiKeyState = isSecretFieldView(cfg.api_key) ? cfg.api_key : null

  const [url, setUrl] = useState<string>(initialUrl)
  const [apiKey, setApiKey] = useState<string>('')
  const [clearApiKey, setClearApiKey] = useState<boolean>(false)
  const [maxParallel, setMaxParallel] = useState<number>(initialMaxParallel)

  const [collisionWarning, setCollisionWarning] = useState<string | null>(null)
  const [test, setTest] = useState<TestState>({ loading: false, result: null })
  const [diagnostics, setDiagnostics] = useState<DiagnosticsState>({
    loading: false,
    data: null,
    error: null,
  })
  const [diagnosticsOpen, setDiagnosticsOpen] = useState<boolean>(false)

  // Connection is "saved" once it has a real id assigned by the backend.
  // For the new-connection wizard, the modal still passes a placeholder
  // Connection object with id === '' so adapter-aware buttons can stay
  // mounted but disabled until the first save completes.
  const isSaved = connection.id !== ''

  // Push config changes upward whenever any field mutates. We always send the
  // full known shape so the modal can ship it verbatim to create/update.
  useEffect(() => {
    const next: Record<string, unknown> = {
      url: url.trim(),
      max_parallel: maxParallel,
    }
    if (apiKey.length > 0) {
      next.api_key = apiKey
    } else if (clearApiKey) {
      next.api_key = null
    }
    onConfigChange(next)
    // We deliberately leave onConfigChange out of the deps — the modal
    // recreates the callback on every render which would otherwise loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, apiKey, clearApiKey, maxParallel])

  // URL collision detection — non-blocking, purely informational.
  useEffect(() => {
    let cancelled = false
    const trimmed = url.trim()
    if (!trimmed) {
      setCollisionWarning(null)
      return
    }
    void (async () => {
      try {
        const all = await llmApi.listConnections()
        if (cancelled) return
        const target = normaliseUrl(trimmed)
        const others = all.filter((c: Connection) => c.id !== connection.id)
        const clash = others.find((c) => {
          const otherUrl = c.config.url
          return typeof otherUrl === 'string' && normaliseUrl(otherUrl) === target
        })
        setCollisionWarning(
          clash
            ? `Diese URL wird bereits von "${clash.display_name}" verwendet.`
            : null,
        )
      } catch {
        // Best-effort — silently swallow.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [url, connection.id])

  async function handleTest() {
    if (!isSaved) return
    setTest({ loading: true, result: null })
    try {
      const res = await llmApi.testConnection(connection.id)
      setTest({ loading: false, result: res })
    } catch (err) {
      setTest({
        loading: false,
        result: { valid: false, error: err instanceof Error ? err.message : 'Test fehlgeschlagen' },
      })
    }
  }

  async function loadDiagnostics() {
    if (!isSaved) return
    setDiagnostics({ loading: true, data: null, error: null })
    try {
      const data = await llmApi.getConnectionDiagnostics(connection.id)
      setDiagnostics({ loading: false, data, error: null })
    } catch (err) {
      setDiagnostics({
        loading: false,
        data: null,
        error: err instanceof Error ? err.message : 'Diagnostics fehlgeschlagen',
      })
    }
  }

  function toggleDiagnostics() {
    const next = !diagnosticsOpen
    setDiagnosticsOpen(next)
    if (next && diagnostics.data === null && !diagnostics.loading) {
      void loadDiagnostics()
    }
  }

  const disabledTooltip = isSaved ? undefined : 'Verbindung zuerst speichern'

  return (
    <div className="space-y-4 text-sm text-white/80">
      {/* URL */}
      <div className="space-y-1">
        <label htmlFor={urlId} className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
          URL
        </label>
        <input
          id={urlId}
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://localhost:11434"
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
        />
        {collisionWarning && (
          <p className="text-[11px] text-amber-300">{collisionWarning}</p>
        )}
      </div>

      {/* API Key */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <label htmlFor={keyId} className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
            API-Key
          </label>
          {apiKeyState?.is_set && !clearApiKey && (
            <span className="text-[10px] font-mono uppercase tracking-wider text-green-400/80">
              gespeichert
            </span>
          )}
        </div>
        <input
          id={keyId}
          type="password"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value)
            if (e.target.value.length > 0) setClearApiKey(false)
          }}
          placeholder={apiKeyState?.is_set ? '••••••••  (leer lassen, um beizubehalten)' : 'Optional'}
          autoComplete="new-password"
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
        />
        {apiKeyState?.is_set && (
          <label className="inline-flex items-center gap-1.5 text-[11px] text-white/50">
            <input
              type="checkbox"
              checked={clearApiKey}
              onChange={(e) => {
                setClearApiKey(e.target.checked)
                if (e.target.checked) setApiKey('')
              }}
              className="h-3 w-3"
            />
            Gespeicherten Key entfernen
          </label>
        )}
      </div>

      {/* max_parallel */}
      <div className="space-y-1">
        <label htmlFor={parId} className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
          Max. parallele Anfragen
        </label>
        <input
          id={parId}
          type="number"
          min={1}
          max={32}
          value={maxParallel}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10)
            if (Number.isFinite(n)) setMaxParallel(Math.max(1, n))
          }}
          className="w-24 rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
        />
      </div>

      {/* Test button */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={handleTest}
          disabled={!isSaved || test.loading}
          title={disabledTooltip}
          className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {test.loading ? 'Teste…' : 'Verbindung testen'}
        </button>
        {test.result && (
          <div
            className={[
              'rounded border px-2 py-1.5 text-[12px]',
              test.result.valid
                ? 'border-green-500/30 bg-green-500/10 text-green-300'
                : 'border-red-500/30 bg-red-500/10 text-red-300',
            ].join(' ')}
          >
            {test.result.valid ? 'Verbindung ok.' : `Fehler: ${test.result.error ?? 'unbekannt'}`}
          </div>
        )}
      </div>

      {/* Diagnostics */}
      <div className="rounded border border-white/8">
        <button
          type="button"
          onClick={toggleDiagnostics}
          disabled={!isSaved}
          title={disabledTooltip}
          className="flex w-full items-center justify-between px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider text-white/50 hover:text-white/80 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <span>Diagnostics</span>
          <span>{diagnosticsOpen ? '−' : '+'}</span>
        </button>
        {diagnosticsOpen && (
          <div className="border-t border-white/8 p-3 text-[11px]">
            {diagnostics.loading && <p className="text-white/60">Lade…</p>}
            {diagnostics.error && <p className="text-red-300">{diagnostics.error}</p>}
            {diagnostics.data && (
              <div className="space-y-3">
                <div>
                  <div className="mb-1 font-mono uppercase tracking-wider text-white/50">ps</div>
                  <pre className="max-h-48 overflow-auto rounded bg-black/40 p-2 text-white/70">
                    {JSON.stringify(diagnostics.data.ps, null, 2)}
                  </pre>
                </div>
                <div>
                  <div className="mb-1 font-mono uppercase tracking-wider text-white/50">tags</div>
                  <pre className="max-h-48 overflow-auto rounded bg-black/40 p-2 text-white/70">
                    {JSON.stringify(diagnostics.data.tags, null, 2)}
                  </pre>
                </div>
                <button
                  type="button"
                  onClick={loadDiagnostics}
                  className="rounded border border-white/15 px-2 py-0.5 text-[11px] text-white/70 hover:bg-white/5"
                >
                  Aktualisieren
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
