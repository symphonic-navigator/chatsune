import { useId, useState } from "react"

interface NewUserFormProps {
  onSubmit: (data: { username: string; email: string; display_name: string; role?: string }) => void
  onCancel: () => void
  submitting: boolean
}

export function NewUserForm({ onSubmit, onCancel, submitting }: NewUserFormProps) {
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [isAdmin, setIsAdmin] = useState(false)

  const usernameId = useId()
  const emailId = useId()
  const displayNameId = useId()
  const adminId = useId()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !email.trim() || !displayName.trim()) return
    onSubmit({
      username: username.trim(),
      email: email.trim(),
      display_name: displayName.trim(),
      role: isAdmin ? "admin" : undefined,
    })
  }

  const inputClass =
    "w-full rounded-lg border border-white/8 bg-elevated px-3 py-1.5 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"

  return (
    <form onSubmit={handleSubmit} className="border-b border-white/6 px-4 py-3">
      <div className="grid grid-cols-[1fr_1fr_1fr_auto_auto] items-end gap-3">
        <div>
          <label htmlFor={usernameId} className="mb-1 block text-[9px] uppercase tracking-[0.15em] text-white/60">
            Username
          </label>
          <input
            id={usernameId}
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="jdoe"
            required
            className={inputClass}
            autoFocus
          />
        </div>

        <div>
          <label htmlFor={emailId} className="mb-1 block text-[9px] uppercase tracking-[0.15em] text-white/60">
            Email
          </label>
          <input
            id={emailId}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="jane@example.com"
            required
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor={displayNameId} className="mb-1 block text-[9px] uppercase tracking-[0.15em] text-white/60">
            Display Name
          </label>
          <input
            id={displayNameId}
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Jane Doe"
            required
            className={inputClass}
          />
        </div>

        <label htmlFor={adminId} className="flex items-center gap-1.5 cursor-pointer pb-0.5">
          <input
            id={adminId}
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => setIsAdmin(e.target.checked)}
            className="accent-gold h-3.5 w-3.5 cursor-pointer"
          />
          <span className="text-[10px] text-white/60">Admin</span>
        </label>

        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={submitting || !username.trim() || !email.trim() || !displayName.trim()}
            className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[11px] font-medium text-gold transition-colors hover:bg-gold/20 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >
            {submitting ? "Creating..." : "CREATE"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-white/8 px-3 py-1.5 text-[11px] text-white/55 transition-colors hover:bg-white/6 hover:text-white/75 cursor-pointer"
          >
            CANCEL
          </button>
        </div>
      </div>
    </form>
  )
}
