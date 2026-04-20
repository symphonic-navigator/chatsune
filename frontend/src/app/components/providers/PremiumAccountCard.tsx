import { useState } from 'react'
import { CAPABILITY_META } from '../../../core/types/providers'
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
} from '../../../core/types/providers'

interface PremiumAccountCardProps {
  definition: PremiumProviderDefinition
  account: PremiumProviderAccount | null
  onSave: (config: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  onTest: () => Promise<void>
  testing?: boolean
}

export function PremiumAccountCard({
  definition,
  account,
  onSave,
  onDelete,
  onTest,
  testing = false,
}: PremiumAccountCardProps) {
  const configured = account !== null
  const status = !configured
    ? 'not set'
    : account.last_test_status === 'ok'
      ? 'ok'
      : account.last_test_status === 'error'
        ? `error: ${account.last_test_error ?? 'see logs'}`
        : 'unverified'

  const [editing, setEditing] = useState(!configured)
  const [keyDraft, setKeyDraft] = useState('')

  async function save() {
    await onSave({ api_key: keyDraft })
    setKeyDraft('')
    setEditing(false)
  }

  return (
    <div className="rounded-lg border border-white/8 bg-white/[0.02] p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <span className="text-[13px] font-semibold text-white/90">
          {definition.display_name}
        </span>
        <span className="text-[11px] font-mono text-white/50">{status}</span>
      </div>

      {editing ? (
        <div className="flex items-center gap-2">
          <input
            type="password"
            placeholder="API key"
            value={keyDraft}
            onChange={(e) => setKeyDraft(e.target.value)}
            className="flex-1 rounded bg-black/30 border border-white/10 px-2 py-1 text-[12px] text-white/90"
          />
          <button
            onClick={() => {
              void save()
            }}
            disabled={!keyDraft}
            className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-30"
          >
            Save
          </button>
          {configured && (
            <button
              onClick={() => {
                setEditing(false)
                setKeyDraft('')
              }}
              className="rounded px-2 py-1 text-[11px] text-white/40 hover:text-white/80"
            >
              Cancel
            </button>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="flex-1 font-mono text-[11px] text-white/40">
            {'\u2022'.repeat(16)}
          </span>
          <button
            onClick={() => setEditing(true)}
            className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5"
          >
            Change
          </button>
          <button
            onClick={() => {
              void onTest()
            }}
            disabled={testing}
            className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-40 disabled:cursor-wait"
          >
            {testing ? 'Testing\u2026' : 'Test'}
          </button>
          <button
            onClick={() => {
              void onDelete()
            }}
            className="rounded px-2 py-1 text-[11px] text-red-400/70 hover:text-red-300"
          >
            Remove
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {definition.capabilities.map((cap) => {
          const meta = CAPABILITY_META[cap]
          return (
            <span
              key={cap}
              title={meta.tooltip}
              className={[
                'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono',
                configured
                  ? 'bg-violet-500/15 text-violet-200 border border-violet-500/30'
                  : 'bg-white/5 text-white/30 border border-white/10',
              ].join(' ')}
            >
              {meta.label}
            </span>
          )
        })}
      </div>
    </div>
  )
}
