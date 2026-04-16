import { useState } from 'react'
import { Sheet } from '../../core/components/Sheet'

/**
 * One-shot reveal of a plaintext Host-Key. The key is shown only in the
 * `HomelabCreatedDto` / `HomelabHostKeyRegeneratedDto` response bodies and
 * is never re-retrievable — so the UI must make it obvious the user should
 * copy it out now, and dismissal requires an explicit "I've saved it".
 *
 * Backdrop click and Escape are still wired (via `Sheet`) so the user can
 * close the modal, but the visual emphasis is squarely on the primary
 * confirm button.
 */
export function HostKeyRevealModal({
  plaintext,
  onClose,
}: {
  plaintext: string
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(plaintext)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard may be unavailable (e.g. http, no user gesture). The user
      // can still select and copy from the <pre>.
    }
  }

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="lg"
      ariaLabel="Host-Key revealed"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-gold">
            Host-Key — shown once
          </h2>
        </div>
        <div className="space-y-4 px-5 py-4">
          <p className="text-[13px] text-amber-300">
            Copy this now. It will not be shown again. Paste it into your
            sidecar's{' '}
            <code className="rounded bg-black/50 px-1 font-mono">.env</code>{' '}
            under{' '}
            <code className="rounded bg-black/50 px-1 font-mono">
              CHATSUNE_HOST_KEY=
            </code>{' '}
            before closing this dialog.
          </p>
          <pre className="overflow-x-auto rounded border border-white/10 bg-black/60 p-3 font-mono text-[12px] text-white/90">
            {plaintext}
          </pre>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-white/8 px-5 py-3">
          <button
            type="button"
            onClick={() => void copy()}
            className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
          >
            {copied ? 'Copied' : 'Copy to clipboard'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded bg-gold/90 px-4 py-1.5 text-[12px] font-semibold text-black hover:bg-gold"
          >
            I've saved it
          </button>
        </div>
      </div>
    </Sheet>
  )
}
