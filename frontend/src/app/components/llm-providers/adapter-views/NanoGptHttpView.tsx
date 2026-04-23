import { useEffect, useId, useState } from 'react'
import type { AdapterViewProps } from '../../../../core/adapters/AdapterViewRegistry'
import type { SecretFieldView } from '../../../../core/types/llm'

function isSecretFieldView(value: unknown): value is SecretFieldView {
  return (
    typeof value === 'object' &&
    value !== null &&
    'is_set' in (value as Record<string, unknown>) &&
    typeof (value as SecretFieldView).is_set === 'boolean'
  )
}

export function NanoGptHttpView({ connection, requiredConfigFields, onConfigChange }: AdapterViewProps) {
  const apiKeyRequired = requiredConfigFields.includes('api_key')
  const urlId = useId()
  const keyId = useId()
  const parId = useId()

  const cfg = connection.config
  const initialBaseUrl = typeof cfg.base_url === 'string' ? cfg.base_url : 'https://api.nano-gpt.com/v1'
  const initialMaxParallel =
    typeof cfg.max_parallel === 'number'
      ? cfg.max_parallel
      : Number(cfg.max_parallel) || 3
  const apiKeyState = isSecretFieldView(cfg.api_key) ? cfg.api_key : null

  const [baseUrl, setBaseUrl] = useState<string>(initialBaseUrl)
  const [apiKey, setApiKey] = useState<string>('')
  const [clearApiKey, setClearApiKey] = useState<boolean>(false)
  const [maxParallel, setMaxParallel] = useState<number>(initialMaxParallel)

  useEffect(() => {
    const next: Record<string, unknown> = {
      base_url: baseUrl.trim(),
      max_parallel: maxParallel,
    }
    if (apiKey.length > 0) {
      next.api_key = apiKey
    } else if (clearApiKey) {
      next.api_key = null
    }
    onConfigChange(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, apiKey, clearApiKey, maxParallel])

  useEffect(() => {
    if (apiKeyState?.is_set && apiKey !== '' && !clearApiKey) {
      setApiKey('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeyState?.is_set])

  return (
    <div className="space-y-4 text-sm text-white/80">
      {/* Base URL */}
      <div className="space-y-1">
        <label htmlFor={urlId} className="block text-[11px] font-mono uppercase tracking-wider text-white/50">
          Base URL
        </label>
        <input
          id={urlId}
          type="url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.nano-gpt.com/v1"
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
        />
        <p className="text-[11px] text-white/40">
          Override only if you are pointing at a self-hosted proxy or a
          regional Nano-GPT endpoint.
        </p>
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
        <p className="text-[11px] text-white/40">
          Generate a key at{' '}
          <span className="font-mono text-white/60">nano-gpt.com</span>
          {' '}under your account's API settings. Without a Nano-GPT
          subscription, subscription-tagged models fall back to pay-per-token
          billing.
        </p>
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
    </div>
  )
}
