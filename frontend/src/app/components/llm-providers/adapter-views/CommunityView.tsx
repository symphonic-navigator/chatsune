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

/**
 * Consumer-side view for a Community Connection. The user pastes the
 * 11-character Homelab-ID (without the ``homelab://`` scheme — that is a
 * UI label only, never stored) and the API-Key they received from the
 * host. Everything else about the homelab (engine type, models, online
 * status) is discovered through CSP at runtime.
 */
export function CommunityView({
  connection,
  requiredConfigFields: _requiredConfigFields,
  onConfigChange,
}: AdapterViewProps) {
  const homelabInputId = useId()
  const apiKeyInputId = useId()

  const cfg = connection.config
  const initialHomelabId = typeof cfg.homelab_id === 'string' ? cfg.homelab_id : ''
  const apiKeyState = isSecretFieldView(cfg.api_key) ? cfg.api_key : null

  const [homelabId, setHomelabId] = useState<string>(initialHomelabId)
  const [apiKey, setApiKey] = useState<string>('')
  const [clearApiKey, setClearApiKey] = useState<boolean>(false)

  // Push config upward whenever anything mutates. The modal owns the save
  // button and forwards the result to the API — the view is a pure editor.
  useEffect(() => {
    const next: Record<string, unknown> = {
      homelab_id: homelabId.trim(),
    }
    if (apiKey.length > 0) {
      next.api_key = apiKey
    } else if (clearApiKey) {
      next.api_key = null
    }
    onConfigChange(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [homelabId, apiKey, clearApiKey])

  // Once the backend confirms the secret is saved, clear the local copy so
  // the input shows the masked placeholder.
  useEffect(() => {
    if (apiKeyState?.is_set && apiKey !== '' && !clearApiKey) {
      setApiKey('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeyState?.is_set])

  const homelabIdLength = homelabId.trim().length
  const homelabIdInvalid = homelabIdLength > 0 && homelabIdLength !== 11

  return (
    <div className="space-y-4 text-sm text-white/80">
      {/* Homelab-ID */}
      <div className="space-y-1">
        <label
          htmlFor={homelabInputId}
          className="block text-[11px] font-mono uppercase tracking-wider text-white/50"
        >
          Homelab-ID
        </label>
        <div className="flex items-center gap-2">
          <span className="rounded bg-black/30 px-2 py-1.5 font-mono text-[12px] text-white/50">
            homelab://
          </span>
          <input
            id={homelabInputId}
            type="text"
            value={homelabId}
            onChange={(e) => setHomelabId(e.target.value)}
            placeholder="Xk7bQ2eJn9m"
            maxLength={11}
            autoComplete="off"
            spellCheck={false}
            className="flex-1 rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-purple/60"
          />
        </div>
        {homelabIdInvalid && (
          <p className="text-[11px] text-amber-300">
            Homelab-ID must be exactly 11 characters.
          </p>
        )}
        <p className="text-[11px] text-white/40">
          The host shares this ID with you. It uniquely identifies their
          homelab; you never need to know its network address.
        </p>
      </div>

      {/* API-Key */}
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
          type="password"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value)
            if (e.target.value.length > 0) setClearApiKey(false)
          }}
          placeholder={
            apiKeyState?.is_set
              ? '••••••••  (leave empty to keep)'
              : 'csapi_…'
          }
          autoComplete="new-password"
          spellCheck={false}
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
          The API-Key restricts which models on the homelab you may use.
          Ask the host if you need access to more.
        </p>
      </div>
    </div>
  )
}
