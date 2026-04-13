import { useState, useCallback } from 'react'
import * as api from './api'

const INPUT = "w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"

interface Props {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function LovenseConfig({ config, onChange }: Props) {
  const [testStatus, setTestStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [testResponse, setTestResponse] = useState<string | null>(null)

  const ip = (config.ip as string) ?? ''

  const handleTest = useCallback(async () => {
    if (!ip.trim()) return
    setTestStatus('loading')
    setTestResponse(null)
    try {
      const result = await api.getToys(ip)
      setTestResponse(JSON.stringify(result, null, 2))
      setTestStatus('success')
    } catch (err) {
      setTestResponse(err instanceof Error ? err.message : String(err))
      setTestStatus('error')
    }
  }, [ip])

  return (
    <div className="flex flex-col gap-4">
      <div>
        <input
          type="text"
          value={ip}
          onChange={(e) => onChange({ ...config, ip: e.target.value })}
          placeholder="192.168.0.92"
          className={INPUT}
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleTest}
          disabled={!ip.trim() || testStatus === 'loading'}
          className={[
            'px-4 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-wider transition-all border',
            ip.trim() && testStatus !== 'loading'
              ? 'border-white/20 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/85 cursor-pointer'
              : 'border-white/8 bg-transparent text-white/25 cursor-not-allowed',
          ].join(' ')}
        >
          {testStatus === 'loading' ? 'Testing...' : 'Test Connection'}
        </button>

        {testStatus === 'success' && (
          <span className="text-[11px] text-green-400/80 font-mono">Connected</span>
        )}
        {testStatus === 'error' && (
          <span className="text-[11px] text-red-400/80 font-mono">Failed</span>
        )}
      </div>

      {testResponse && (
        <pre className={[
          'rounded-lg border px-3 py-2 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-32 overflow-y-auto',
          testStatus === 'success'
            ? 'border-green-500/20 bg-green-500/[0.04] text-green-400/80'
            : 'border-red-500/20 bg-red-500/[0.04] text-red-400/80',
        ].join(' ')}>
          {testResponse}
        </pre>
      )}
    </div>
  )
}
