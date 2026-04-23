import { useState } from 'react'

interface Props {
  username: string
  onRecover: (newPassword: string, recoveryKey: string) => Promise<void>
  onDecline: () => Promise<void>
}

/**
 * Shown after a login attempt returned {status: "recovery_required"} — typically
 * because an administrator reset this user's password. The user must either
 * enter their recovery key (and pick a new password at the same time) or
 * explicitly decline, which deactivates the account.
 */
export function RecoveryKeyPrompt({ username, onRecover, onDecline }: Props) {
  const [recoveryKey, setRecoveryKey] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmed, setConfirmed] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showDecline, setShowDecline] = useState(false)

  const submit = async () => {
    setError(null)
    if (newPassword !== confirmed) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      await onRecover(newPassword, recoveryKey)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Recovery failed')
    } finally {
      setBusy(false)
    }
  }

  const confirmDecline = async () => {
    setBusy(true)
    try {
      await onDecline()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Decline failed')
    } finally {
      setBusy(false)
    }
  }

  if (showDecline) {
    return (
      <div className="space-y-3 max-w-md mx-auto">
        <h3 className="text-lg font-semibold">Without your recovery key</h3>
        <p className="text-sm opacity-80 leading-relaxed">
          If you do not have your recovery key, your encrypted data cannot be recovered.
          Your account will be deactivated, and only the administrator can destroy it
          and recreate a fresh account for you. Any encrypted data you had will be lost.
        </p>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowDecline(false)}
            disabled={busy}
            className="flex-1 py-2 bg-white/10 rounded hover:bg-white/20 disabled:opacity-40 transition"
          >
            Back
          </button>
          <button
            type="button"
            onClick={confirmDecline}
            disabled={busy}
            className="flex-1 py-2 bg-red-600 rounded hover:bg-red-700 disabled:opacity-40 transition"
          >
            {busy ? 'Deactivating…' : 'I understand — deactivate'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 max-w-md mx-auto">
      <h3 className="text-lg font-semibold">Recovery required</h3>
      <p className="text-sm opacity-80 leading-relaxed">
        An administrator reset the password for <span className="font-mono">{username}</span>.
        To recover your data, enter your recovery key and choose a new password.
      </p>
      <input
        type="text"
        className="w-full p-2 rounded bg-white/5 font-mono placeholder:opacity-40"
        placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
        value={recoveryKey}
        onChange={(e) => setRecoveryKey(e.target.value)}
        autoComplete="off"
        autoCapitalize="characters"
      />
      <input
        type="password"
        className="w-full p-2 rounded bg-white/5 placeholder:opacity-40"
        placeholder="Choose a new password"
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
        autoComplete="new-password"
      />
      <input
        type="password"
        className="w-full p-2 rounded bg-white/5 placeholder:opacity-40"
        placeholder="Confirm new password"
        value={confirmed}
        onChange={(e) => setConfirmed(e.target.value)}
        autoComplete="new-password"
      />
      {error && <p className="text-red-400 text-sm">{error}</p>}
      <button
        type="button"
        disabled={busy || !recoveryKey || !newPassword || !confirmed}
        onClick={submit}
        className="w-full py-2 bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded font-medium transition"
      >
        {busy ? 'Recovering…' : 'Recover'}
      </button>
      <button
        type="button"
        onClick={() => setShowDecline(true)}
        disabled={busy}
        className="w-full text-sm underline opacity-70 hover:opacity-100 disabled:opacity-40 transition"
      >
        I do not have my recovery key
      </button>
    </div>
  )
}
