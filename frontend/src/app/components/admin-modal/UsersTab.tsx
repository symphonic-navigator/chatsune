import { useState, useEffect, useCallback } from "react"
import type { UserDto, CreateUserResponse } from "../../../core/types/auth"
import { usersApi } from "../../../core/api/users"
import { useAuthStore } from "../../../core/store/authStore"
import { NewUserForm } from "./NewUserForm"

interface ResetConfirm {
  userId: string
  username: string
}

export function UsersTab() {
  const currentUser = useAuthStore((s) => s.user)

  const [users, setUsers] = useState<UserDto[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [showNewForm, setShowNewForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const [generatedPw, setGeneratedPw] = useState<{ username: string; password: string; expiresAt: number } | null>(null)
  const [pwCountdown, setPwCountdown] = useState(0)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [resetConfirm, setResetConfirm] = useState<ResetConfirm | null>(null)
  const [resetSuccess, setResetSuccess] = useState<string | null>(null)

  // Fetch users
  const fetchUsers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await usersApi.list(0, 200)
      setUsers(res.users)
      setTotal(res.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch users")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  // Password banner countdown.
  // setInterval is intentional here: the banner shows a live "Disappears in Ns"
  // counter that ticks every second until the 60s window expires. A one-shot
  // setTimeout would not give the user the running visual feedback.
  useEffect(() => {
    if (!generatedPw) return
    const remaining = Math.max(0, Math.ceil((generatedPw.expiresAt - Date.now()) / 1000))
    setPwCountdown(remaining)

    const interval = setInterval(() => {
      const r = Math.max(0, Math.ceil((generatedPw.expiresAt - Date.now()) / 1000))
      setPwCountdown(r)
      if (r <= 0) {
        setGeneratedPw(null)
        clearInterval(interval)
      }
    }, 1000)

    return () => clearInterval(interval)
  }, [generatedPw])

  function showPassword(username: string, password: string) {
    setGeneratedPw({ username, password, expiresAt: Date.now() + 60_000 })
    setCopied(false)
    setCopyError(null)
  }

  async function handleCopy() {
    if (!generatedPw) return
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(generatedPw.password)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API may be blocked (insecure context, denied permission, etc.)
      setCopyError("Copy failed — please select and copy manually")
    }
  }

  // Create user
  async function handleCreate(data: { username: string; email: string; display_name: string; role?: string }) {
    setSubmitting(true)
    setError(null)
    try {
      const res: CreateUserResponse = await usersApi.create(data)
      setUsers((prev) => [...prev, res.user])
      setTotal((prev) => prev + 1)
      setShowNewForm(false)
      showPassword(res.user.username, res.generated_password)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user")
    } finally {
      setSubmitting(false)
    }
  }

  // Toggle role
  async function handleToggleRole(user: UserDto) {
    if (user.role === "master_admin") return
    if (user.id === currentUser?.id) return
    const newRole = user.role === "admin" ? "user" : "admin"
    try {
      const updated = await usersApi.update(user.id, { role: newRole })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role")
    }
  }

  // Toggle lock
  async function handleToggleLock(user: UserDto) {
    if (user.role === "master_admin") return
    if (user.id === currentUser?.id) return
    try {
      const updated = await usersApi.update(user.id, { is_active: !user.is_active })
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to toggle lock")
    }
  }

  // Reset password — first step: open confirmation dialog
  function handleResetPasswordStart(user: UserDto) {
    if (user.id === currentUser?.id) return
    setResetConfirm({ userId: user.id, username: user.username })
  }

  // Reset password — confirmed: call API
  async function handleResetPasswordConfirm() {
    if (!resetConfirm) return
    const { userId, username } = resetConfirm
    setResetConfirm(null)
    try {
      const res = await usersApi.resetPassword(userId)
      setUsers((prev) => prev.map((u) => (u.id === res.user.id ? res.user : u)))
      setResetSuccess(username)
      setTimeout(() => setResetSuccess(null), 8000)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password")
    }
  }

  // Deactivate (delete)
  async function handleDeactivate(userId: string) {
    if (userId === currentUser?.id) return
    try {
      await usersApi.deactivate(userId)
      setUsers((prev) => prev.filter((u) => u.id !== userId))
      setTotal((prev) => prev - 1)
      setConfirmDeleteId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to deactivate user")
      setConfirmDeleteId(null)
    }
  }

  const isSelf = (user: UserDto) => user.id === currentUser?.id
  const isMaster = (user: UserDto) => user.role === "master_admin"

  // Loading state
  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Loading users...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/6 px-4 py-2.5">
        <span className="text-[10px] uppercase tracking-[0.15em] text-white/60">
          User Registry
        </span>
        <button
          type="button"
          onClick={() => setShowNewForm((v) => !v)}
          className={[
            "rounded-lg border px-3 py-1.5 text-[11px] font-medium transition-colors cursor-pointer",
            showNewForm
              ? "border-white/8 text-white/60 hover:bg-white/6"
              : "border-gold/30 bg-gold/10 text-gold hover:bg-gold/20",
          ].join(" ")}
        >
          {showNewForm ? "Cancel" : "+ New User"}
        </button>
      </div>

      {/* New user form */}
      {showNewForm && (
        <NewUserForm
          onSubmit={handleCreate}
          onCancel={() => setShowNewForm(false)}
          submitting={submitting}
        />
      )}

      {/* Generated password banner (new-user creation only) */}
      {generatedPw && (
        <div className="flex flex-col gap-1 border-b border-green-400/20 bg-green-400/5 px-4 py-2.5">
          <div className="flex items-center gap-3">
            <span className="text-[11px] text-green-400">
              Password for <span className="font-medium">{generatedPw.username}</span>:
            </span>
            <code className="rounded bg-white/6 px-2 py-0.5 text-[12px] font-mono text-white/80">
              {generatedPw.password}
            </code>
            <button
              type="button"
              onClick={handleCopy}
              aria-label={copied ? "Password copied to clipboard" : "Copy password to clipboard"}
              className="rounded border border-white/8 px-2 py-0.5 text-[10px] text-white/60 transition-colors hover:bg-white/6 hover:text-white/80 cursor-pointer"
            >
              {copied ? "COPIED" : "COPY"}
            </button>
            <span className="text-[10px] text-white/60">
              Disappears in {pwCountdown}s
            </span>
            <button
              type="button"
              onClick={() => setGeneratedPw(null)}
              aria-label="Dismiss password banner"
              className="ml-auto text-[10px] text-white/60 hover:text-white/80 transition-colors cursor-pointer"
            >
              Dismiss
            </button>
          </div>
          {copyError && (
            <div role="alert" aria-live="polite" className="text-[10px] text-red-400">
              {copyError}
            </div>
          )}
        </div>
      )}

      {/* Reset-password confirmation dialog */}
      {resetConfirm && (
        <div className="flex flex-col gap-2 border-b border-amber-400/20 bg-amber-400/5 px-4 py-3">
          <p className="text-[12px] text-amber-300 leading-relaxed">
            <span className="font-semibold">Warning</span> — This reset does not recover the
            user&apos;s data. If <span className="font-mono">{resetConfirm.username}</span> does
            not have their recovery key, all their encrypted data will become permanently
            inaccessible.
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleResetPasswordConfirm}
              className="rounded bg-amber-400/20 border border-amber-400/30 px-2.5 py-1 text-[11px] font-medium text-amber-300 hover:bg-amber-400/30 transition-colors cursor-pointer"
            >
              Yes, reset
            </button>
            <button
              type="button"
              onClick={() => setResetConfirm(null)}
              className="rounded px-2.5 py-1 text-[11px] text-white/60 hover:text-white/80 transition-colors cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Reset-password success banner */}
      {resetSuccess && (
        <div className="flex items-center justify-between border-b border-green-400/20 bg-green-400/5 px-4 py-2.5">
          <span className="text-[11px] text-green-400">
            Password reset for <span className="font-medium">{resetSuccess}</span>. The user will
            need their recovery key to sign in.
          </span>
          <button
            type="button"
            onClick={() => setResetSuccess(null)}
            className="ml-4 text-[10px] text-green-400/60 hover:text-green-400 transition-colors cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="flex items-center justify-between border-b border-red-400/20 bg-red-400/5 px-4 py-2">
          <span className="text-[11px] text-red-400">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-[10px] text-red-400/60 hover:text-red-400 transition-colors cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* User list */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 z-10 bg-surface">
            <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-white/60">
              <th className="px-4 py-2 font-medium">User</th>
              <th className="px-4 py-2 font-medium">Email</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium">Ops</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-10 text-center">
                  <div className="flex flex-col items-center gap-3">
                    <span className="text-[12px] text-white/60">No users yet</span>
                    {!showNewForm && (
                      <button
                        type="button"
                        onClick={() => setShowNewForm(true)}
                        className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[11px] font-medium text-gold transition-colors hover:bg-gold/20 cursor-pointer"
                      >
                        Create your first user
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )}
            {users.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                isSelf={isSelf(user)}
                isMaster={isMaster(user)}
                confirmDeleteId={confirmDeleteId}
                onToggleRole={() => handleToggleRole(user)}
                onToggleLock={() => handleToggleLock(user)}
                onResetPassword={() => handleResetPasswordStart(user)}
                onDeactivateStart={() => setConfirmDeleteId(user.id)}
                onDeactivateConfirm={() => handleDeactivate(user.id)}
                onDeactivateCancel={() => setConfirmDeleteId(null)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="flex items-center border-t border-white/6 px-4 py-2">
        <span className="text-[10px] text-white/60">
          {total} {total === 1 ? "user" : "users"}
        </span>
      </div>
    </div>
  )
}

// ─── Row component ──────────────────────────────────────────────────

interface UserRowProps {
  user: UserDto
  isSelf: boolean
  isMaster: boolean
  confirmDeleteId: string | null
  onToggleRole: () => void
  onToggleLock: () => void
  onResetPassword: () => void
  onDeactivateStart: () => void
  onDeactivateConfirm: () => void
  onDeactivateCancel: () => void
}

function UserRow({
  user,
  isSelf,
  isMaster,
  confirmDeleteId,
  onToggleRole,
  onToggleLock,
  onResetPassword,
  onDeactivateStart,
  onDeactivateConfirm,
  onDeactivateCancel,
}: UserRowProps) {
  const isConfirmingDelete = confirmDeleteId === user.id
  const opsDisabled = isSelf || isMaster

  const roleBtnClass = [
    "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors",
    isSelf || isMaster
      ? "text-white/30 cursor-default"
      : "cursor-pointer hover:bg-white/6",
    user.role === "admin"
      ? "text-blue-400"
      : user.role === "master_admin"
        ? "text-purple-400"
        : "text-white/55",
  ].join(" ")

  const roleLabel =
    user.role === "master_admin"
      ? "master"
      : user.role === "admin"
        ? "admin"
        : "user"

  return (
    <tr className="group border-b border-white/6 transition-colors hover:bg-white/4">
      {/* User column: username + display_name + badges */}
      <td className="px-4 py-2">
        <div className="flex items-center gap-2">
          <div className="flex flex-col">
            <span className="text-[12px] text-white/80">{user.username}</span>
            <span className="text-[10px] text-white/60">{user.display_name}</span>
          </div>
          {isMaster && (
            <span className="rounded bg-purple-400/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-purple-400 border border-purple-400/25">
              Master
            </span>
          )}
          {!user.is_active && (
            <span className="rounded bg-red-400/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-red-400 border border-red-400/25">
              Locked
            </span>
          )}
          {isSelf && (
            <span className="rounded bg-white/6 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-white/30">
              You
            </span>
          )}
        </div>
      </td>

      {/* Email */}
      <td className="px-4 py-2 text-[12px] text-white/55">
        {user.email}
      </td>

      {/* Role — clickable toggle */}
      <td className="px-4 py-2">
        <button
          type="button"
          onClick={onToggleRole}
          disabled={isSelf || isMaster}
          className={roleBtnClass}
          title={
            isSelf
              ? "Cannot change own role"
              : isMaster
                ? "Cannot change master admin role"
                : `Click to toggle between user/admin`
          }
        >
          {roleLabel}
        </button>
      </td>

      {/* Ops — visible on hover */}
      <td className="px-4 py-2">
        <div
          aria-live="polite"
          className="flex items-center gap-1 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
        >
          {/* Lock/Unlock */}
          <button
            type="button"
            onClick={onToggleLock}
            disabled={opsDisabled}
            className={[
              "rounded px-1.5 py-0.5 text-[10px] transition-colors",
              opsDisabled
                ? "text-white/15 cursor-not-allowed"
                : user.is_active
                  ? "text-white/55 hover:bg-white/6 hover:text-white/75 cursor-pointer"
                  : "text-green-400 hover:bg-green-400/10 cursor-pointer",
            ].join(" ")}
            aria-label={user.is_active ? `Lock user ${user.username}` : `Unlock user ${user.username}`}
            title={opsDisabled ? "Cannot modify" : user.is_active ? "Lock user" : "Unlock user"}
          >
            {user.is_active ? "LOCK" : "UNLOCK"}
          </button>

          {/* Reset password */}
          <button
            type="button"
            onClick={onResetPassword}
            disabled={isSelf}
            className={[
              "rounded px-1.5 py-0.5 text-[10px] transition-colors",
              isSelf
                ? "text-white/15 cursor-not-allowed"
                : "text-white/55 hover:bg-white/6 hover:text-white/75 cursor-pointer",
            ].join(" ")}
            aria-label={`Reset password for ${user.username}`}
            title={isSelf ? "Cannot reset own password" : "Reset password"}
          >
            RESET
          </button>

          {/* Deactivate — two-step confirm */}
          {!isConfirmingDelete ? (
            <button
              type="button"
              onClick={onDeactivateStart}
              disabled={opsDisabled}
              className={[
                "rounded px-1.5 py-0.5 text-[10px] transition-colors",
                opsDisabled
                  ? "text-white/15 cursor-not-allowed"
                  : "text-red-400/60 hover:bg-red-400/10 hover:text-red-400 cursor-pointer",
              ].join(" ")}
              aria-label={`Deactivate user ${user.username}`}
              title={opsDisabled ? "Cannot deactivate" : "Deactivate user"}
            >
              DEL
            </button>
          ) : (
            <>
              <span className="sr-only" role="status">
                Confirm deactivation of {user.username}
              </span>
              <button
                type="button"
                onClick={onDeactivateConfirm}
                aria-label={`Confirm deactivation of ${user.username}`}
                className="rounded bg-red-400/15 px-1.5 py-0.5 text-[10px] text-red-400 hover:bg-red-400/25 transition-colors cursor-pointer"
              >
                CONFIRM
              </button>
              <button
                type="button"
                onClick={onDeactivateCancel}
                aria-label="Cancel deactivation"
                className="rounded px-1.5 py-0.5 text-[10px] text-white/60 hover:text-white/80 transition-colors cursor-pointer"
              >
                CANCEL
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}
