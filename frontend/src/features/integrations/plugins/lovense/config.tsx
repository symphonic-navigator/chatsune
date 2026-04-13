import { useState, useCallback } from 'react'
import * as api from './api'
import type { ToyInfo, Action } from './api'

const INPUT = "w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"
const INPUT_SM = "w-20 bg-white/[0.03] border border-white/10 rounded-lg px-3 py-1.5 text-white/75 font-mono text-[12px] outline-none focus:border-gold/30 transition-colors text-center"
const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"
const BTN_BASE = 'px-4 py-1.5 rounded-lg font-mono text-[11px] uppercase tracking-wider transition-all border'
const BTN_ACTIVE = 'border-white/20 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/85 cursor-pointer'
const BTN_DISABLED = 'border-white/8 bg-transparent text-white/25 cursor-not-allowed'
const OPTION_STYLE: React.CSSProperties = { background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }

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
          <div className="flex gap-1.5 mt-1 flex-wrap">
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

function TestPanel({ ip, toys }: { ip: string; toys: ToyInfo[] }) {
  const [action, setAction] = useState<string>('Vibrate')
  const [toy, setToy] = useState<string>('')
  const [strength, setStrength] = useState(5)
  const [timeSec, setTimeSec] = useState(3)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  const maxStr = api.maxStrength(action as Action)

  const handleSend = useCallback(async () => {
    setSending(true)
    setResult(null)
    try {
      const res = await api.functionCommand(ip, {
        action: action as Action,
        strength: Math.min(strength, maxStr),
        timeSec,
        toy: toy || undefined,
      })
      setResult({ ok: true, text: JSON.stringify(res, null, 2) })
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setSending(false)
    }
  }, [ip, action, strength, timeSec, toy, maxStr])

  const handleStop = useCallback(async () => {
    setSending(true)
    setResult(null)
    try {
      const res = toy
        ? await api.stopToy(ip, toy)
        : await api.stopAll(ip)
      setResult({ ok: true, text: JSON.stringify(res, null, 2) })
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : String(err) })
    } finally {
      setSending(false)
    }
  }, [ip, toy])

  return (
    <div className="flex flex-col gap-3">
      {/* Action + Toy row */}
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className={LABEL}>Action</label>
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="bg-white/[0.03] border border-white/10 rounded-lg px-3 py-1.5 text-white/75 font-mono text-[12px] outline-none focus:border-gold/30"
          >
            {api.ACTIONS.map((a) => (
              <option key={a} value={a} style={OPTION_STYLE}>{a} (0-{api.maxStrength(a)})</option>
            ))}
          </select>
        </div>
        <div>
          <label className={LABEL}>Toy</label>
          <select
            value={toy}
            onChange={(e) => setToy(e.target.value)}
            className="bg-white/[0.03] border border-white/10 rounded-lg px-3 py-1.5 text-white/75 font-mono text-[12px] outline-none focus:border-gold/30"
          >
            <option value="" style={OPTION_STYLE}>All toys</option>
            {toys.map((t) => (
              <option key={t.id} value={t.id} style={OPTION_STYLE}>
                {t.nickName || t.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Strength + Time row */}
      <div className="flex gap-2 items-end">
        <div>
          <label className={LABEL}>Strength (0-{maxStr})</label>
          <input
            type="number"
            min={0}
            max={maxStr}
            value={strength}
            onChange={(e) => setStrength(Math.max(0, Math.min(maxStr, parseInt(e.target.value, 10) || 0)))}
            className={INPUT_SM}
          />
        </div>
        <div>
          <label className={LABEL}>Seconds (0=indef.)</label>
          <input
            type="number"
            min={0}
            value={timeSec}
            onChange={(e) => setTimeSec(Math.max(0, parseInt(e.target.value, 10) || 0))}
            className={INPUT_SM}
          />
        </div>
      </div>

      {/* Send + Stop buttons */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleSend}
          disabled={sending}
          className={[BTN_BASE, sending ? BTN_DISABLED : BTN_ACTIVE].join(' ')}
        >
          {sending ? 'Sending...' : 'Send'}
        </button>
        <button
          type="button"
          onClick={handleStop}
          disabled={sending}
          className={[
            BTN_BASE,
            sending
              ? BTN_DISABLED
              : 'border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 cursor-pointer',
          ].join(' ')}
        >
          Stop{toy ? '' : ' All'}
        </button>
      </div>

      {/* Result */}
      {result && (
        <pre className={[
          'rounded-lg border px-3 py-2 text-[11px] font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap max-h-24 overflow-y-auto',
          result.ok
            ? 'border-green-500/20 bg-green-500/[0.04] text-green-400/80'
            : 'border-red-500/20 bg-red-500/[0.04] text-red-400/80',
        ].join(' ')}>
          {result.text}
        </pre>
      )}
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
          className={[BTN_BASE, ip.trim() && status !== 'loading' ? BTN_ACTIVE : BTN_DISABLED].join(' ')}
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

      {/* Function Test Panel — shown when connected */}
      {status === 'success' && (
        <div className="pt-2 border-t border-white/6">
          <label className={LABEL}>Function Test</label>
          <TestPanel ip={ip} toys={toys} />
        </div>
      )}
    </div>
  )
}
