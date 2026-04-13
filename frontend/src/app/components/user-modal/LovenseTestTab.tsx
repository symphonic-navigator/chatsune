import { useState, useCallback } from 'react'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"
const INPUT = "w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"

const STORAGE_KEY = 'chatsune:lovense-ip'

function buildLovenseUrl(ip: string): string {
  const dashed = ip.trim().replace(/\./g, '-')
  return `https://${dashed}.lovense.club:30010/command`
}

export function LovenseTestTab() {
  const [ip, setIp] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '')
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [response, setResponse] = useState<string | null>(null)

  const saveIp = useCallback((value: string) => {
    setIp(value)
    if (value.trim()) {
      localStorage.setItem(STORAGE_KEY, value.trim())
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [])

  const handleGetToys = useCallback(async () => {
    const trimmed = ip.trim()
    if (!trimmed) return

    setStatus('loading')
    setResponse(null)

    try {
      const url = buildLovenseUrl(trimmed)
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: 'GetToys' }),
      })

      const text = await res.text()

      // Try to pretty-print JSON, fall back to raw text
      let display: string
      try {
        display = JSON.stringify(JSON.parse(text), null, 2)
      } catch {
        display = text
      }

      setStatus(res.ok ? 'success' : 'error')
      setResponse(res.ok ? display : `HTTP ${res.status}\n${display}`)
    } catch (err) {
      setStatus('error')
      setResponse(err instanceof Error ? err.message : String(err))
    }
  }, [ip])

  const resolvedUrl = ip.trim() ? buildLovenseUrl(ip) : null

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl overflow-y-auto">
      <p className="text-[11px] text-white/40 font-mono leading-relaxed">
        Test harness for the Lovense Game Mode API. Enter the IP address of the
        phone running Lovense Remote on your local network.
      </p>

      {/* IP input */}
      <div>
        <label className={LABEL}>Phone IP Address</label>
        <input
          type="text"
          value={ip}
          onChange={(e) => saveIp(e.target.value)}
          placeholder="192.168.0.92"
          className={INPUT}
        />
      </div>

      {/* Resolved URL preview */}
      {resolvedUrl && (
        <div>
          <label className={LABEL}>Resolved URL</label>
          <p className="text-[11px] text-white/30 font-mono break-all">{resolvedUrl}</p>
        </div>
      )}

      {/* Get Toys button */}
      <button
        type="button"
        onClick={handleGetToys}
        disabled={!ip.trim() || status === 'loading'}
        className={[
          'px-5 py-2 rounded-lg font-mono text-[11px] uppercase tracking-wider transition-all border self-start',
          ip.trim() && status !== 'loading'
            ? 'border-gold/60 bg-gold/12 text-gold hover:bg-gold/20 cursor-pointer'
            : 'border-white/8 bg-transparent text-white/25 cursor-not-allowed',
        ].join(' ')}
      >
        {status === 'loading' ? 'Requesting...' : 'Get Toys'}
      </button>

      {/* Response display */}
      {response !== null && (
        <div>
          <label className={LABEL}>
            {status === 'success' ? 'Response' : 'Error'}
          </label>
          <pre
            className={[
              'rounded-lg border px-4 py-3 text-[12px] font-mono leading-relaxed overflow-x-auto whitespace-pre-wrap',
              status === 'success'
                ? 'border-green-500/20 bg-green-500/[0.04] text-green-400/80'
                : 'border-red-500/20 bg-red-500/[0.04] text-red-400/80',
            ].join(' ')}
          >
            {response}
          </pre>
        </div>
      )}
    </div>
  )
}
