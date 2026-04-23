import { useId, useState } from "react"
import type { KeyboardEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "../../core/hooks/useAuth"
import { useAuthStore } from "../../core/store/authStore"
import { safeLocalStorage } from "../../core/utils/safeStorage"

const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[14px] text-white/85 placeholder-white/20 outline-none transition-colors focus:border-white/25 focus:bg-white/8"

const labelClass = "mb-1 block text-[12px] font-medium text-white/40"
const subtitleClass = "mb-1.5 block text-[11px] text-white/50"
const hintClass = "mt-1 block text-[11px] text-white/45"
const errorHintClass = "mt-1 block text-[11px] text-red-400/80"

interface FieldErrors {
  current_password?: string
  new_password?: string
}

function extractFieldErrors(err: unknown): { fields: FieldErrors; general: string | null } {
  if (err instanceof Error) {
    try {
      const parsed = JSON.parse(err.message) as unknown
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const detail = (parsed as { detail: unknown }).detail
        if (Array.isArray(detail)) {
          const fields: FieldErrors = {}
          for (const item of detail) {
            if (
              item &&
              typeof item === "object" &&
              "loc" in item &&
              "msg" in item &&
              Array.isArray((item as { loc: unknown }).loc)
            ) {
              const loc = (item as { loc: unknown[] }).loc
              const msg = String((item as { msg: unknown }).msg)
              const key = loc[loc.length - 1]
              if (key === "current_password" || key === "new_password") {
                fields[key] = msg
              }
            }
          }
          if (Object.keys(fields).length > 0) {
            return { fields, general: null }
          }
        }
        // Backend may send {"detail": "string"} for known errors
        if (typeof detail === "string") {
          return { fields: {}, general: detail }
        }
      }
    } catch {
      // not JSON
    }
    return { fields: {}, general: err.message }
  }
  return { fields: {}, general: "Unknown error" }
}

export default function ChangePasswordPage() {
  const currentId = useId()
  const newId = useId()
  const confirmId = useId()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [capsLock, setCapsLock] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const { changePassword } = useAuth()
  const username = useAuthStore((s) => s.user?.username ?? "")
  const navigate = useNavigate()

  const newTooShort = newPassword.length > 0 && newPassword.length < 8
  const mismatch =
    confirmPassword.length > 0 && newPassword !== confirmPassword
  const sameAsCurrent =
    newPassword.length > 0 &&
    currentPassword.length > 0 &&
    newPassword === currentPassword

  function handleKey(e: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState("CapsLock"))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setFieldErrors({})
    if (newTooShort) {
      setError("Your new incantation must be at least 8 characters")
      return
    }
    if (mismatch) {
      setError("The two new incantations do not match")
      return
    }
    if (sameAsCurrent) {
      setError("Your new incantation must differ from the old one")
      return
    }
    setIsLoading(true)
    try {
      await changePassword({
        username,
        current_password: currentPassword,
        new_password: newPassword,
      })
      const last = safeLocalStorage.getItem("chatsune_last_route")
      navigate(last ?? "/personas", { replace: true })
    } catch (err) {
      const { fields, general } = extractFieldErrors(err)
      setFieldErrors(fields)
      setError(general ?? "Could not renew your incantation")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
      <div className="w-full max-w-sm rounded-xl border border-white/8 bg-surface p-6 shadow-2xl sm:p-8">
        <div className="mb-6 text-center">
          <span className="text-3xl">🦊</span>
          <h1 className="mt-2 text-xl font-semibold text-white/85">
            Renew your Incantation
          </h1>
          <p className="mt-1 text-[13px] text-white/30">
            Your spell has expired — choose a new one
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor={currentId} className={labelClass}>
              Old Incantation
            </label>
            <span className={subtitleClass}>current password</span>
            <input
              id={currentId}
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              onKeyDown={handleKey}
              onKeyUp={handleKey}
              required
              autoFocus
              autoComplete="current-password"
              aria-label="current password"
              aria-invalid={fieldErrors.current_password ? true : undefined}
              aria-describedby={
                fieldErrors.current_password ? `${currentId}-error` : undefined
              }
              className={inputClass}
            />
            {fieldErrors.current_password && (
              <span id={`${currentId}-error`} className={errorHintClass}>
                {fieldErrors.current_password}
              </span>
            )}
          </div>

          <div>
            <label htmlFor={newId} className={labelClass}>
              New Incantation
            </label>
            <span className={subtitleClass}>at least 8 characters</span>
            <input
              id={newId}
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              onKeyDown={handleKey}
              onKeyUp={handleKey}
              required
              autoComplete="new-password"
              aria-label="new password"
              aria-invalid={
                newTooShort || sameAsCurrent || fieldErrors.new_password
                  ? true
                  : undefined
              }
              aria-describedby={`${newId}-hint`}
              className={inputClass}
            />
            <span
              id={`${newId}-hint`}
              className={
                newTooShort || sameAsCurrent || fieldErrors.new_password
                  ? errorHintClass
                  : hintClass
              }
            >
              {fieldErrors.new_password ??
                (newTooShort
                  ? `Too short — ${8 - newPassword.length} more character${8 - newPassword.length === 1 ? "" : "s"}`
                  : sameAsCurrent
                    ? "Must differ from your old incantation"
                    : "Minimum 8 characters")}
            </span>
          </div>

          <div>
            <label htmlFor={confirmId} className={labelClass}>
              Confirm Incantation
            </label>
            <span className={subtitleClass}>repeat new password</span>
            <input
              id={confirmId}
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              onKeyDown={handleKey}
              onKeyUp={handleKey}
              required
              autoComplete="new-password"
              aria-label="confirm new password"
              aria-invalid={mismatch ? true : undefined}
              aria-describedby={mismatch ? `${confirmId}-hint` : undefined}
              className={inputClass}
            />
            {mismatch && (
              <span id={`${confirmId}-hint`} className={errorHintClass}>
                The two incantations do not match
              </span>
            )}
          </div>

          {capsLock && (
            <span role="alert" className="block text-[11px] text-amber-400/80">
              Caps Lock is on
            </span>
          )}

          {error && !Object.keys(fieldErrors).length && (
            <p
              role="alert"
              className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-[13px] text-red-400"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full rounded-lg bg-white/10 py-2 text-[14px] font-medium text-white/80 transition-colors hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Renewing..." : "Renew"}
          </button>
        </form>
      </div>
    </div>
  )
}
