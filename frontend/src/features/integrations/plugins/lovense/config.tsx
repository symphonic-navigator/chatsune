import { useState, useCallback } from 'react'
import * as api from './api'
import type { ToyInfo } from './api'

const INPUT = "w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"
const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

interface Props {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

function CapabilityTag({ name }: { name: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase border border-purple-400/30 bg-purple-400/10 text-purple-300/80">
      {name}
    </span>
  )
}

function StatusDot({ online }: { online: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${online ? 'bg-green-400' : 'bg-white/20'}`}
      title={online ? 'Online' : 'Offline'}
    />
  )
}

function BatteryIndicator({ level }: { level: number }) {
  const colour = level > 50 ? 'text-green-400/80' : level > 20 ? 'text-yellow-400/80' : 'text-red-400/80'
  return <span className={`text-[11px] font-mono ${colour}`}>{level}%</span>
}

function ToyCard({ toy }: { toy: ToyInfo }) {
  const displayName = toy.nickName || toy.name

  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg border border-white/8 bg-white/[0.02]">
      <div className="flex items-center gap-2.5 min-w-0">
        <StatusDot online={toy.status === 'online'} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-mono text-white/80 truncate">{displayName}</span>
            {toy.nickName && toy.name !== toy.nickName && (
              <span className="text-[10px] text-white/30 font-mono">({toy.name})</span>
            )}
          </div>
          <div className="flex gap-1.5 mt-1">
            {toy.capabilities.map((cap) => (
              <CapabilityTag key={cap} name={cap} />
            ))}
          </div>
        </div>
      </div>
      <BatteryIndicator level={toy.battery} />
    </div>
  )
}

export function LovenseConfig({ config, onChange }: Props) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [toys, setToys] = useState<ToyInfo[]>([])
  const [platform, setPlatform] = useState<string>('')

  const ip = (config.ip as string) ?? ''

  const handleGetToys = useCallback(async () => {
    if (!ip.trim()) return
    setStatus('loading')
    setError(null)
    try {
      const raw = await api.getToys(ip)
      const parsed = api.parseGetToysResponse(raw)
      if (!parsed.ok) {
        setStatus('error')
        setError('Unexpected response from Lovense Remote')
        return
      }
      setToys(parsed.toys)
      setPlatform(parsed.platform)
      setStatus('success')
    } catch (err) {
      setStatus('error')
      setError(err instanceof Error ? err.message : String(err))
      setToys([])
    }
  }, [ip])

  return (
    <div className="flex flex-col gap-4">
      {/* IP input */}
      <div>
        <input
          type="text"
          value={ip}
          onChange={(e) => onChange({ ...config, ip: e.target.value })}
          placeholder="192.168.0.92"
          className={INPUT}
        />
      </div>

      {/* Get Toys button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleGetToys}
          disabled={!ip.trim() || status === 'loading'}
          className={[
            'px-4 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-wider transition-all border',
            ip.trim() && status !== 'loading'
              ? 'border-white/20 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/85 cursor-pointer'
              : 'border-white/8 bg-transparent text-white/25 cursor-not-allowed',
          ].join(' ')}
        >
          {status === 'loading' ? 'Scanning...' : 'Get Toys'}
        </button>

        {status === 'success' && (
          <span className="text-[11px] text-green-400/80 font-mono">
            {toys.length === 0 ? 'Connected (no toys)' : `${toys.length} toy${toys.length !== 1 ? 's' : ''} found`}
          </span>
        )}
        {status === 'error' && (
          <span className="text-[11px] text-red-400/80 font-mono">Failed</span>
        )}
      </div>

      {/* Error display */}
      {error && (
        <p className="text-[11px] text-red-400/70 font-mono">{error}</p>
      )}

      {/* Toy Inspector */}
      {status === 'success' && toys.length > 0 && (
        <div>
          <label className={LABEL}>
            Connected Toys
            {platform && <span className="text-white/30 normal-case ml-2">via {platform}</span>}
          </label>
          <div className="flex flex-col gap-2">
            {toys.map((toy) => (
              <ToyCard key={toy.id} toy={toy} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
