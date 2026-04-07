import { useId, useState } from "react"
import type { KeyboardEvent } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "../../core/hooks/useAuth"
import { useAuthStore } from "../../core/store/authStore"
import { safeLocalStorage } from "../../core/utils/safeStorage"

export default function LoginPage() {
  const isSetupComplete = useAuthStore((s) => s.isSetupComplete)

  if (isSetupComplete === false) {
    return <SetupForm />
  }

  return <LoginForm />
}

const inputClass =
  "w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[14px] text-white/85 placeholder-white/20 outline-none transition-colors focus:border-white/25 focus:bg-white/8"

const labelClass = "mb-1 block text-[12px] font-medium text-white/40"
const subtitleClass = "mb-1.5 block text-[11px] text-white/50"
const hintClass = "mt-1 block text-[11px] text-white/45"
const errorHintClass = "mt-1 block text-[11px] text-red-400/80"

interface FieldErrors {
  username?: string
  password?: string
  email?: string
  pin?: string
}

function extractFieldErrors(err: unknown): { fields: FieldErrors; general: string | null } {
  if (err instanceof Error) {
    // Try parse JSON-shaped backend errors like {"detail":[{"loc":["body","email"],"msg":"..."}]}
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
              if (key === "username" || key === "password" || key === "email" || key === "pin") {
                fields[key] = msg
              }
            }
          }
          if (Object.keys(fields).length > 0) {
            return { fields, general: null }
          }
        }
      }
    } catch {
      // not JSON
    }
    return { fields: {}, general: err.message }
  }
  return { fields: {}, general: "Unknown error" }
}

function LoginForm() {
  const usernameId = useId()
  const passwordId = useId()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [capsLock, setCapsLock] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  function handlePasswordKey(e: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState("CapsLock"))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setFieldErrors({})
    setIsLoading(true)
    try {
      await login({ username, password })
      const last = safeLocalStorage.getItem("chatsune_last_route")
      navigate(last ?? "/personas", { replace: true })
    } catch (err) {
      const { fields, general } = extractFieldErrors(err)
      setFieldErrors(fields)
      setError(general ?? "Invalid username or password")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base">
      <div className="w-full max-w-sm rounded-xl border border-white/8 bg-surface p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <span className="text-3xl">🦊</span>
          <h1 className="mt-2 text-xl font-semibold text-white/85">Welcome</h1>
          <p className="mt-1 text-[13px] text-white/30">Cast your spell to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor={usernameId} className={labelClass}>
              Omen
            </label>
            <span className={subtitleClass}>username</span>
            <input
              id={usernameId}
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              autoComplete="username"
              aria-label="username"
              aria-invalid={fieldErrors.username ? true : undefined}
              aria-describedby={fieldErrors.username ? `${usernameId}-error` : undefined}
              className={inputClass}
            />
            {fieldErrors.username && (
              <span id={`${usernameId}-error`} className={errorHintClass}>
                {fieldErrors.username}
              </span>
            )}
          </div>

          <div>
            <label htmlFor={passwordId} className={labelClass}>
              Incantation
            </label>
            <span className={subtitleClass}>password</span>
            <input
              id={passwordId}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handlePasswordKey}
              onKeyUp={handlePasswordKey}
              required
              autoComplete="current-password"
              aria-label="password"
              aria-invalid={fieldErrors.password ? true : undefined}
              aria-describedby={
                [
                  fieldErrors.password ? `${passwordId}-error` : null,
                  capsLock ? `${passwordId}-caps` : null,
                ]
                  .filter(Boolean)
                  .join(" ") || undefined
              }
              className={inputClass}
            />
            {capsLock && (
              <span
                id={`${passwordId}-caps`}
                role="alert"
                className="mt-1 block text-[11px] text-amber-400/80"
              >
                Caps Lock is on
              </span>
            )}
            {fieldErrors.password && (
              <span id={`${passwordId}-error`} className={errorHintClass}>
                {fieldErrors.password}
              </span>
            )}
          </div>

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
            {isLoading ? "Casting..." : "Cast"}
          </button>
        </form>
      </div>
    </div>
  )
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PIN_REGEX = /^\d{4,8}$/

function SetupForm() {
  const pinId = useId()
  const usernameId = useId()
  const emailId = useId()
  const passwordId = useId()
  const [pin, setPin] = useState("")
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [capsLock, setCapsLock] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const { setup } = useAuth()
  const setSetupComplete = useAuthStore((s) => s.setSetupComplete)
  const navigate = useNavigate()

  const passwordTooShort = password.length > 0 && password.length < 8
  const emailInvalid = email.length > 0 && !EMAIL_REGEX.test(email)
  const pinInvalid = pin.length > 0 && !PIN_REGEX.test(pin)

  function handlePasswordKey(e: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState("CapsLock"))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setFieldErrors({})
    if (passwordTooShort || emailInvalid || pinInvalid) {
      setError("Please fix the highlighted fields before continuing")
      return
    }
    setIsLoading(true)
    try {
      await setup({ pin, username, email, password })
      setSetupComplete(true)
      navigate("/personas", { replace: true })
    } catch (err) {
      const { fields, general } = extractFieldErrors(err)
      setFieldErrors(fields)
      setError(general ?? "Setup failed")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base">
      <div className="w-full max-w-sm rounded-xl border border-white/8 bg-surface p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <span className="text-3xl">🦊</span>
          <h1 className="mt-2 text-xl font-semibold text-white/85">First Time Setup</h1>
          <p className="mt-1 text-[13px] text-white/30">Create the master admin account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor={pinId} className={labelClass}>
              Setup PIN
            </label>
            <span className={subtitleClass}>4-8 digits from server console</span>
            <input
              id={pinId}
              type="password"
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              required
              autoFocus
              autoComplete="off"
              inputMode="numeric"
              aria-label="setup PIN"
              aria-invalid={pinInvalid || fieldErrors.pin ? true : undefined}
              aria-describedby={`${pinId}-hint`}
              className={inputClass}
            />
            <span
              id={`${pinId}-hint`}
              className={pinInvalid || fieldErrors.pin ? errorHintClass : hintClass}
            >
              {fieldErrors.pin ?? (pinInvalid ? "PIN must be 4-8 digits" : "Numeric, 4-8 digits")}
            </span>
          </div>

          <div>
            <label htmlFor={usernameId} className={labelClass}>
              Username
            </label>
            <span className={subtitleClass}>your sign-in name</span>
            <input
              id={usernameId}
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="username"
              aria-label="username"
              aria-invalid={fieldErrors.username ? true : undefined}
              aria-describedby={fieldErrors.username ? `${usernameId}-error` : undefined}
              className={inputClass}
            />
            {fieldErrors.username && (
              <span id={`${usernameId}-error`} className={errorHintClass}>
                {fieldErrors.username}
              </span>
            )}
          </div>

          <div>
            <label htmlFor={emailId} className={labelClass}>
              Email
            </label>
            <span className={subtitleClass}>used for account recovery</span>
            <input
              id={emailId}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              aria-label="email"
              aria-invalid={emailInvalid || fieldErrors.email ? true : undefined}
              aria-describedby={
                emailInvalid || fieldErrors.email ? `${emailId}-hint` : undefined
              }
              className={inputClass}
            />
            {(emailInvalid || fieldErrors.email) && (
              <span id={`${emailId}-hint`} className={errorHintClass}>
                {fieldErrors.email ?? "Enter a valid email address"}
              </span>
            )}
          </div>

          <div>
            <label htmlFor={passwordId} className={labelClass}>
              Password
            </label>
            <span className={subtitleClass}>at least 8 characters</span>
            <input
              id={passwordId}
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handlePasswordKey}
              onKeyUp={handlePasswordKey}
              required
              aria-label="password"
              aria-invalid={passwordTooShort || fieldErrors.password ? true : undefined}
              aria-describedby={`${passwordId}-hint`}
              className={inputClass}
            />
            <span
              id={`${passwordId}-hint`}
              className={
                passwordTooShort || fieldErrors.password ? errorHintClass : hintClass
              }
            >
              {fieldErrors.password ??
                (passwordTooShort
                  ? `Too short — ${8 - password.length} more character${8 - password.length === 1 ? "" : "s"}`
                  : "Minimum 8 characters")}
            </span>
            {capsLock && (
              <span role="alert" className="mt-1 block text-[11px] text-amber-400/80">
                Caps Lock is on
              </span>
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
            disabled={isLoading}
            className="w-full rounded-lg bg-white/10 py-2 text-[14px] font-medium text-white/80 transition-colors hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Setting up..." : "Create Master Admin"}
          </button>
        </form>
      </div>
    </div>
  )
}
