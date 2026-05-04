import { useEffect, useId, useState } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"

import { authApi } from "../../core/api/auth"
import { ApiError } from "../../core/api/client"
import { RecoveryKeyModal } from "../../features/auth/RecoveryKeyModal"
import { useAuthStore } from "../../core/store/authStore"
import { FoxIcon } from "../../core/components/symbols"

type Phase =
  | { kind: "validating" }
  | { kind: "invalid"; reason: "expired" | "used" | "not_found" }
  | { kind: "form" }
  | { kind: "submitting" }
  | { kind: "recovery-key"; key: string }
  | { kind: "success" }

const REASON_TEXT: Record<"expired" | "used" | "not_found", string> = {
  expired: "This invitation link has expired.",
  used: "This invitation link has already been used.",
  not_found: "This invitation link is no longer valid.",
}

// see also: LoginPage.tsx — this file deliberately duplicates the setup form's
// styling constants and crypto wiring. Both will be lifted to a shared hook
// on the third use (rule of three).
const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[14px] text-white/85 placeholder-white/20 outline-none transition-colors focus:border-white/25 focus:bg-white/8"

const labelClass = "mb-1 block text-[12px] font-medium text-white/40"
const errorHintClass = "mt-1 block text-[11px] text-red-400/80"

export default function RegisterPage() {
  const { token = "" } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  // Invitations are for new accounts only — redirect logged-in users away
  // immediately so they cannot accidentally create a duplicate account.
  useEffect(() => {
    if (isAuthenticated) {
      navigate("/personas", { replace: true })
    }
  }, [isAuthenticated, navigate])

  const usernameId = useId()
  const emailId = useId()
  const displayNameId = useId()
  const passwordId = useId()
  const confirmId = useId()
  const usernameErrorId = useId()
  const passwordErrorId = useId()
  const confirmErrorId = useId()

  const [phase, setPhase] = useState<Phase>({ kind: "validating" })
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<{ field: string; msg: string } | null>(null)

  // Validate the token on mount
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await authApi.validateInvitation(token)
        if (cancelled) return
        if (r.valid) {
          setPhase({ kind: "form" })
        } else {
          setPhase({ kind: "invalid", reason: r.reason ?? "not_found" })
        }
      } catch {
        if (!cancelled) setPhase({ kind: "invalid", reason: "not_found" })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  const passwordStrength = scorePassword(password)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setFieldError(null)
    if (password !== confirm) {
      setFieldError({ field: "confirm", msg: "Passwords do not match." })
      return
    }
    if (passwordStrength < 3) {
      setFieldError({ field: "password", msg: "Password is too weak." })
      return
    }
    setPhase({ kind: "submitting" })
    try {
      const { recoveryKey } = await authApi.registerWithInvitation(token, {
        username,
        email,
        displayName,
        password,
      })
      setPhase({ kind: "recovery-key", key: recoveryKey })
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 410) {
          setPhase({ kind: "invalid", reason: "used" })
          return
        }
        if (err.status === 409) {
          setFieldError({ field: "username", msg: "Username or email already taken." })
          setPhase({ kind: "form" })
          return
        }
      }
      setError("Something went wrong. Please try again.")
      setPhase({ kind: "form" })
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-base px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
      <div className="w-full max-w-sm rounded-xl border border-white/8 bg-surface p-6 shadow-2xl sm:p-8">
        <div className="mb-6 text-center">
          <FoxIcon className="mx-auto" style={{ fontSize: '30px' }} />
          <h1 className="mt-2 text-xl font-semibold text-white/85">Create Account</h1>
          <p className="mt-1 text-[13px] text-white/30">You have been invited to Chatsune</p>
        </div>

        {phase.kind === "validating" && (
          <p className="text-center text-[13px] text-white/50">Checking invitation…</p>
        )}

        {phase.kind === "invalid" && (
          <div className="space-y-4 text-center">
            <p className="text-[14px] text-white/70">{REASON_TEXT[phase.reason]}</p>
            <Link
              to="/login"
              className="inline-block rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-[13px] text-white/70 transition-colors hover:bg-white/10"
            >
              Go to login
            </Link>
          </div>
        )}

        {(phase.kind === "form" || phase.kind === "submitting") && (
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor={usernameId} className={labelClass}>Username</label>
              <input
                id={usernameId}
                type="text"
                required
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                aria-describedby={fieldError?.field === "username" ? usernameErrorId : undefined}
                aria-invalid={fieldError?.field === "username" || undefined}
                className={inputClass}
              />
              {fieldError?.field === "username" && (
                <span id={usernameErrorId} role="alert" className={errorHintClass}>{fieldError.msg}</span>
              )}
            </div>

            <div>
              <label htmlFor={emailId} className={labelClass}>Email</label>
              <input
                id={emailId}
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor={displayNameId} className={labelClass}>Display name</label>
              <input
                id={displayNameId}
                type="text"
                required
                autoComplete="name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className={inputClass}
              />
            </div>

            <div>
              <label htmlFor={passwordId} className={labelClass}>Password</label>
              <div className="relative">
                <input
                  id={passwordId}
                  type={showPassword ? "text" : "password"}
                  required
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-describedby={fieldError?.field === "password" ? passwordErrorId : undefined}
                  aria-invalid={fieldError?.field === "password" || undefined}
                  className={`${inputClass} pr-16`}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-white/40 hover:text-white/70 transition-colors"
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
              <StrengthBar score={passwordStrength} />
              {fieldError?.field === "password" && (
                <span id={passwordErrorId} role="alert" className={errorHintClass}>{fieldError.msg}</span>
              )}
            </div>

            <div>
              <label htmlFor={confirmId} className={labelClass}>Confirm password</label>
              <input
                id={confirmId}
                type={showPassword ? "text" : "password"}
                required
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                aria-describedby={fieldError?.field === "confirm" ? confirmErrorId : undefined}
                aria-invalid={fieldError?.field === "confirm" || undefined}
                className={inputClass}
              />
              {fieldError?.field === "confirm" && (
                <span id={confirmErrorId} role="alert" className={errorHintClass}>{fieldError.msg}</span>
              )}
            </div>

            {error && (
              <p
                role="alert"
                className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-[13px] text-red-400"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={phase.kind === "submitting"}
              className="w-full rounded-lg bg-white/10 py-2 text-[14px] font-medium text-white/80 transition-colors hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {phase.kind === "submitting" ? "Creating account…" : "Create account"}
            </button>
          </form>
        )}

        {phase.kind === "recovery-key" && (
          <RecoveryKeyModal
            recoveryKey={phase.key}
            onAcknowledged={() => setPhase({ kind: "success" })}
          />
        )}

        {phase.kind === "success" && (
          <div className="space-y-4 text-center">
            <p className="text-[14px] text-white/70">
              Account created. You can now log in.
            </p>
            <button
              type="button"
              onClick={() => navigate("/login")}
              className="inline-block rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-[13px] text-white/70 transition-colors hover:bg-white/10"
            >
              Go to login
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// score password strength 0–4.
// Not a security control — server-side crypto means the plaintext never
// leaves the client. This just guards against obvious weak choices and
// confirm-mismatch typos.
function scorePassword(pw: string): number {
  let score = 0
  if (pw.length >= 12) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw)) score++
  if (/[^A-Za-z0-9]/.test(pw)) score++
  return score
}

const STRENGTH_COLOURS = [
  "bg-rose-500/60",
  "bg-orange-500/60",
  "bg-yellow-500/60",
  "bg-emerald-500/60",
] as const

function StrengthBar({ score }: { score: number }) {
  return (
    <div className="mt-2 flex gap-1">
      {([0, 1, 2, 3] as const).map((i) => (
        <div
          key={i}
          className={`h-1 flex-1 rounded ${i < score ? STRENGTH_COLOURS[Math.min(score - 1, 3)] : "bg-white/10"}`}
        />
      ))}
    </div>
  )
}
