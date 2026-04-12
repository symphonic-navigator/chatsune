import { useId, useState } from 'react'
import type { McpGatewayConfig } from './types'

export interface GatewayEditDialogProps {
  mode: 'create' | 'edit'
  gateway?: McpGatewayConfig
  tier: 'remote' | 'local'
  onSave: (gateway: McpGatewayConfig) => void
  onDelete?: () => void
  onCancel: () => void
}

function normaliseNamespace(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

const INPUT =
  'w-full rounded-lg border border-white/8 bg-white/[0.03] px-3 py-1.5 text-[12px] text-white/80 placeholder-white/25 outline-none focus:border-[rgba(137,180,250,0.35)] transition-colors'
const LABEL = 'block text-[11px] text-white/50 mb-1'

export function GatewayEditDialog({
  mode,
  gateway,
  onSave,
  onDelete,
  onCancel,
}: GatewayEditDialogProps) {
  const [name, setName] = useState(gateway?.name ?? '')
  const [url, setUrl] = useState(gateway?.url ?? '')
  const [apiKey, setApiKey] = useState(gateway?.api_key ?? '')
  const [enabled, setEnabled] = useState(gateway?.enabled ?? true)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [nameError, setNameError] = useState<string | null>(null)
  const [urlError, setUrlError] = useState<string | null>(null)

  const nameId = useId()
  const urlId = useId()
  const apiKeyId = useId()
  const enabledId = useId()

  const namespace = normaliseNamespace(name)

  function validate(): boolean {
    let valid = true
    if (!name.trim()) {
      setNameError('Name is required.')
      valid = false
    } else {
      setNameError(null)
    }
    if (!url.trim().match(/^https?:\/\//)) {
      setUrlError('URL must start with http:// or https://')
      valid = false
    } else {
      setUrlError(null)
    }
    return valid
  }

  function handleSave() {
    if (!validate()) return
    onSave({
      id: gateway?.id ?? '',
      name: name.trim(),
      url: url.trim(),
      api_key: apiKey.trim() || null,
      enabled,
      disabled_tools: gateway?.disabled_tools ?? [],
      server_configs: gateway?.server_configs ?? {},
      tool_overrides: gateway?.tool_overrides ?? [],
    })
  }

  function handleDelete() {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    onDelete?.()
  }

  return (
    <div className="rounded-xl border border-white/8 bg-[rgba(255,255,255,0.03)] p-5 flex flex-col gap-4">
      {/* Name */}
      <div>
        <label htmlFor={nameId} className={LABEL}>
          Name
        </label>
        <input
          id={nameId}
          type="text"
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            if (nameError) setNameError(null)
          }}
          placeholder="My MCP Gateway"
          autoFocus
          className={INPUT}
        />
        {nameError ? (
          <p className="mt-1 text-[10px] text-[rgba(243,139,168,0.9)]">{nameError}</p>
        ) : namespace ? (
          <p className="mt-1 text-[10px] text-white/35 font-mono">
            Tools will appear as{' '}
            <span className="text-white/55">{namespace}__tool_name</span>
          </p>
        ) : null}
      </div>

      {/* URL */}
      <div>
        <label htmlFor={urlId} className={LABEL}>
          URL
        </label>
        <input
          id={urlId}
          type="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value)
            if (urlError) setUrlError(null)
          }}
          placeholder="https://mcp.example.com"
          className={`${INPUT} font-mono`}
        />
        {urlError && (
          <p className="mt-1 text-[10px] text-[rgba(243,139,168,0.9)]">{urlError}</p>
        )}
      </div>

      {/* API Key */}
      <div>
        <label htmlFor={apiKeyId} className={LABEL}>
          API Key{' '}
          <span className="text-white/30">(optional)</span>
        </label>
        <input
          id={apiKeyId}
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="No authentication"
          autoComplete="off"
          className={INPUT}
        />
      </div>

      {/* Enabled toggle — edit mode only */}
      {mode === 'edit' && (
        <div className="flex items-center gap-3">
          <span className={LABEL + ' mb-0'}>Enabled</span>
          <button
            id={enabledId}
            type="button"
            role="switch"
            aria-checked={enabled}
            onClick={() => setEnabled((v) => !v)}
            className={[
              'relative inline-flex h-5 w-9 items-center rounded-full border transition-colors focus:outline-none',
              enabled
                ? 'border-[rgba(137,180,250,0.5)] bg-[rgba(137,180,250,0.2)]'
                : 'border-white/15 bg-white/[0.05]',
            ].join(' ')}
          >
            <span
              className={[
                'inline-block h-3.5 w-3.5 rounded-full transition-transform',
                enabled
                  ? 'translate-x-4 bg-[rgba(137,180,250,0.9)]'
                  : 'translate-x-0.5 bg-white/30',
              ].join(' ')}
            />
          </button>
          <span className="text-[11px] text-white/40">{enabled ? 'Active' : 'Disabled'}</span>
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-2 pt-1">
        {/* Delete — edit mode only */}
        {mode === 'edit' && onDelete && (
          <button
            type="button"
            onClick={handleDelete}
            className={[
              'rounded-lg border px-3 py-1.5 text-[11px] font-mono transition-colors cursor-pointer',
              confirmDelete
                ? 'border-[rgba(243,139,168,0.6)] bg-[rgba(243,139,168,0.15)] text-[rgba(243,139,168,1)]'
                : 'border-[rgba(243,139,168,0.25)] bg-[rgba(243,139,168,0.07)] text-[rgba(243,139,168,0.75)] hover:bg-[rgba(243,139,168,0.12)]',
            ].join(' ')}
          >
            {confirmDelete ? 'ARE YOU SURE?' : 'DELETE'}
          </button>
        )}

        <div className="flex-1" />

        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-white/8 px-3 py-1.5 text-[11px] font-mono text-white/45 transition-colors hover:bg-white/6 hover:text-white/65 cursor-pointer"
        >
          CANCEL
        </button>
        <button
          type="button"
          onClick={handleSave}
          className="rounded-lg border border-[rgba(137,180,250,0.35)] bg-[rgba(137,180,250,0.1)] px-3 py-1.5 text-[11px] font-mono text-[rgba(137,180,250,0.9)] transition-colors hover:bg-[rgba(137,180,250,0.18)] cursor-pointer"
        >
          {mode === 'create' ? 'ADD GATEWAY' : 'SAVE'}
        </button>
      </div>
    </div>
  )
}
