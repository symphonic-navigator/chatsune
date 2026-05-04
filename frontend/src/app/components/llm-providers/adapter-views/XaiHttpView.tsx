import { useEffect, useId, useState } from 'react'
import type { AdapterViewProps } from '../../../../core/adapters/AdapterViewRegistry'
import type { SecretFieldView } from '../../../../core/types/llm'
import { SECRET_INPUT_STYLE, SECRET_INPUT_NO_AUTOFILL } from '../../../../core/utils/secretInputStyle'

function isSecretFieldView(value: unknown): value is SecretFieldView {
  return (
    typeof value === 'object' &&
    value !== null &&
    'is_set' in (value as Record<string, unknown>) &&
    typeof (value as SecretFieldView).is_set === 'boolean'
  )
}

export function XaiHttpView({ connection, requiredConfigFields, onConfigChange }: AdapterViewProps) {
  const apiKeyRequired = requiredConfigFields.includes('api_key')
  const urlId = useId()
  const keyId = useId()
  const parId = useId()

  const cfg = connection.config
  const initialUrl = typeof cfg.url === 'string' ? cfg.url : 'https://api.x.ai/v1'
  const initialMaxParallel =
    typeof cfg.max_parallel === 'number'
      ? cfg.max_parallel
      : Number(cfg.max_parallel) || 4
  const apiKeyState = isSecretFieldView(cfg.api_key) ? cfg.api_key : null

  const [url, setUrl] = useState<string>(initialUrl)
  const [apiKey, setApiKey] = useState<string>('')
  const [clearApiKey, setClearApiKey] = useState<boolean>(false)
  const [maxParallel, setMaxParallel] = useState<number>(initialMaxParallel)

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, apiKey, clearApiKey, maxParallel])

  useEffect(() => {
    if (apiKeyState?.is_set && apiKey !== '' && !clearApiKey) {
      setApiKey('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeyState?.is_set])

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
          placeholder="https://api.x.ai/v1"
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
        />
        <p className="text-[11px] text-white/40">
          xAI routes requests to the nearest region automatically. Override
          only if you are pointing at a regional endpoint or a compatible proxy.
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
          type="text"
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
          required={apiKeyRequired}
          style={SECRET_INPUT_STYLE}
          {...SECRET_INPUT_NO_AUTOFILL}
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
        <p className="text-[11px] text-white/40">
          xAI's published limit is 1,800 rpm / 10M tpm — four concurrent
          streams has huge headroom.
        </p>
      </div>
    </div>
  )
}
