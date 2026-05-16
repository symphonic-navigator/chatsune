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

/**
 * Connection-config view for Chutes AI. A single api_key field — Chutes
 * runs a single managed endpoint and we never let users override the
 * URL. Only TEE-flagged models with >=80k context are surfaced in the
 * picker; the explanatory text below the field reflects that.
 */
export function ChutesHttpView({
  connection,
  requiredConfigFields: _requiredConfigFields,
  onConfigChange,
}: AdapterViewProps) {
  const apiKeyInputId = useId()

  const cfg = connection.config
  const apiKeyState = isSecretFieldView(cfg.api_key) ? cfg.api_key : null

  const [apiKey, setApiKey] = useState<string>('')
  const [clearApiKey, setClearApiKey] = useState<boolean>(false)

  useEffect(() => {
    const next: Record<string, unknown> = {}
    if (apiKey.length > 0) {
      next.api_key = apiKey
    } else if (clearApiKey) {
      next.api_key = null
    }
    onConfigChange(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, clearApiKey])

  useEffect(() => {
    if (apiKeyState?.is_set && apiKey !== '' && !clearApiKey) {
      setApiKey('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeyState?.is_set])

  return (
    <div className="space-y-4 text-sm text-white/80">
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <label
            htmlFor={apiKeyInputId}
            className="block text-[11px] font-mono uppercase tracking-wider text-white/50"
          >
            API-Key<span className="text-red-400"> *</span>
          </label>
          {apiKeyState?.is_set && !clearApiKey && (
            <span className="text-[10px] font-mono uppercase tracking-wider text-green-400/80">
              saved
            </span>
          )}
        </div>
        <input
          id={apiKeyInputId}
          type="text"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value)
            if (e.target.value.length > 0) setClearApiKey(false)
          }}
          placeholder={
            apiKeyState?.is_set
              ? '••••••••  (leave empty to keep)'
              : 'cpk_…'
          }
          style={SECRET_INPUT_STYLE}
          {...SECRET_INPUT_NO_AUTOFILL}
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-purple/60"
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
          Get a Chutes API-Key from chutes.ai. Only models running in a
          Trusted Execution Environment (TEE) appear in the picker —
          your prompts are hardware-isolated and even Chutes operators
          cannot read them.
        </p>
      </div>
    </div>
  )
}
