import { useEffect, useMemo, useState } from "react"

interface Props {
  token: string
  expiresAt: string // ISO 8601 from backend
  onClose: () => void
}

/**
 * Shown after an admin generates an invitation link. The link is NOT
 * retrievable again — the user must copy it before closing the dialog.
 */
export function InvitationLinkDialog({ token, expiresAt, onClose }: Props) {
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)

  const url = useMemo(
    () => `${window.location.origin}/register/${token}`,
    [token],
  )

  const expiresFormatted = useMemo(() => {
    try {
      return new Date(expiresAt).toLocaleString()
    } catch {
      return expiresAt
    }
  }, [expiresAt])

  async function copy() {
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API may be blocked — user can still copy manually from the input
      setCopyError("Copy failed — please select and copy manually")
    }
  }

  // Esc to close (after they have presumably copied)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-md rounded-lg border border-white/8 bg-surface p-6 text-white/80">
        <h2 className="mb-3 text-[13px] font-medium text-white/90">
          New invitation link
        </h2>

        <p className="mb-2 text-[12px] text-white/60">
          Share this link with the new user. It is valid for 24 hours and can
          be used exactly once.
        </p>

        <p className="mb-4 text-[11px] text-amber-300">
          Save it before closing — you cannot retrieve it again.
        </p>

        <input
          type="text"
          readOnly
          value={url}
          onFocus={(e) => e.target.select()}
          className="mb-3 w-full rounded-lg border border-white/8 bg-elevated px-3 py-2 font-mono text-[11px] text-white/80 outline-none"
        />

        <div className="mb-4 flex gap-2">
          <button
            type="button"
            onClick={copy}
            className="flex-1 rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[11px] font-medium text-gold transition-colors hover:bg-gold/20 cursor-pointer"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-white/8 px-3 py-1.5 text-[11px] text-white/55 transition-colors hover:bg-white/6 hover:text-white/75 cursor-pointer"
          >
            Close
          </button>
        </div>

        {copyError && (
          <p role="alert" className="mb-3 text-[10px] text-red-400">
            {copyError}
          </p>
        )}

        <p className="text-[10px] text-white/40">Expires: {expiresFormatted}</p>
      </div>
    </div>
  )
}
