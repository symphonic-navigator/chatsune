import { useState } from 'react'

interface Props {
  recoveryKey: string
  onAcknowledged: () => void
}

/**
 * One-shot modal shown immediately after signup or after a legacy-user migration.
 * The recovery key is the user's only path back to their data if they forget
 * their password. This modal is non-dismissable until the user confirms they
 * have saved the key safely.
 */
export function RecoveryKeyModal({ recoveryKey, onAcknowledged }: Props) {
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(recoveryKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore — user will use download fallback
    }
  }

  const download = () => {
    const body = [
      'Chatsune recovery key',
      '',
      recoveryKey,
      '',
      'Keep this safe. If you forget your password, this is the only way',
      'to recover your encrypted data.',
      '',
    ].join('\n')
    const blob = new Blob([body], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'chatsune-recovery-key.txt'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-[#0f0d16] text-white rounded-lg p-6 max-w-lg w-full space-y-4 border border-white/10 shadow-2xl">
        <h2 className="text-xl font-semibold">Your recovery key</h2>
        <p className="text-sm opacity-80 leading-relaxed">
          If you ever forget your password, this is the only way to recover your encrypted data.
          Save it now — you will not be shown it again.
        </p>
        <pre className="font-mono text-center text-base md:text-lg bg-black/40 p-4 rounded select-all break-all">
          {recoveryKey}
        </pre>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={copy}
            className="flex-1 py-2 bg-white/10 rounded hover:bg-white/20 transition"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button
            type="button"
            onClick={download}
            className="flex-1 py-2 bg-white/10 rounded hover:bg-white/20 transition"
          >
            Download as .txt
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={saved}
            onChange={(e) => setSaved(e.target.checked)}
            className="w-4 h-4"
          />
          <span>I have saved this recovery key in a safe place.</span>
        </label>
        <button
          type="button"
          disabled={!saved}
          onClick={onAcknowledged}
          className="w-full py-2 bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded font-medium transition"
        >
          Continue
        </button>
      </div>
    </div>
  )
}
