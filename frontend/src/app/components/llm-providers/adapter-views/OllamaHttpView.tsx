import { useEffect, useId, useMemo, useState } from 'react'
import type { AdapterViewProps } from '../../../../core/adapters/AdapterViewRegistry'
import { llmApi } from '../../../../core/api/llm'
import type { Connection, SecretFieldView } from '../../../../core/types/llm'
import { OllamaModelsPanel, type OllamaEndpoints } from '../../ollama/OllamaModelsPanel'
import type {
  OllamaPsResponse,
  OllamaTagsResponse,
} from '../../../../core/api/ollamaLocal'

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

export function OllamaHttpView({ connection, requiredConfigFields, onConfigChange }: AdapterViewProps) {
  const apiKeyRequired = requiredConfigFields.includes('api_key')
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

  // Connection is "saved" once it has a real id assigned by the backend.
  // For the new-connection wizard, the modal still passes a placeholder
  // Connection object with id === '' so adapter-aware buttons can stay
  // mounted but disabled until the first save completes.
  const isSaved = connection.id !== ''
  const connectionId = connection.id

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

  // After a successful save, the redacted config reports is_set=true. Clear
  // any typed-in value so the input shows the masked placeholder + saved badge.
  useEffect(() => {
    if (apiKeyState?.is_set && apiKey !== '' && !clearApiKey) {
      setApiKey('')
    }
    // Only react to the is_set transition, not every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeyState?.is_set])

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
            ? `You already have a connection to this URL (slug: ${clash.slug}). This may cause unexpected queuing at the backend.`
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

  // Per-connection endpoint bag for the shared models panel. Memoised on the
  // connection id so the panel's effects (which depend on `endpoints`) do not
  // re-fire on every parent render. The backend's diagnostics endpoint bundles
  // ps + tags in one call; we split the two halves so the panel's polling
  // loops can fire them independently without double-fetching.
  const endpoints: OllamaEndpoints | null = useMemo(() => {
    if (!isSaved) return null
    return {
      ps: async () =>
        (await llmApi.getConnectionDiagnostics(connectionId, 'ollama_http')).ps as OllamaPsResponse,
      tags: async () =>
        (await llmApi.getConnectionDiagnostics(connectionId, 'ollama_http')).tags as OllamaTagsResponse,
      pull: (slug) => llmApi.pullModel(connectionId, slug),
      cancelPull: (pullId) => llmApi.cancelModelPull(connectionId, pullId),
      deleteModel: (name) => llmApi.deleteConnectionModel(connectionId, name),
      listPulls: () => llmApi.listConnectionPulls(connectionId),
    }
  }, [isSaved, connectionId])

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
            API key{apiKeyRequired && <span className="text-red-400"> *</span>}
          </label>
          {apiKeyState?.is_set && !clearApiKey && (
            <span className="text-[10px] font-mono uppercase tracking-wider text-green-400/80">
              saved
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
          placeholder={
            apiKeyState?.is_set
              ? '••••••••  (leave empty to keep)'
              : apiKeyRequired ? 'Required' : 'Optional'
          }
          autoComplete="new-password"
          required={apiKeyRequired}
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
            Remove saved key
          </label>
        )}
      </div>

      {/* max_parallel */}
      <div className="space-y-1">
        <label htmlFor={parId} className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
          Max parallel requests
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

      {/* Models panel (replaces the old Diagnostics dropdown) */}
      {isSaved && endpoints && (
        <div className="rounded border border-white/8 overflow-hidden">
          <OllamaModelsPanel scope={`connection:${connectionId}`} endpoints={endpoints} />
        </div>
      )}
    </div>
  )
}
