import { useState } from 'react'
import { Sheet } from '../../core/components/Sheet'

/**
 * One-shot reveal of a plaintext API-Key. Mirrors `HostKeyRevealModal`
 * in structure; distinct copy because the audience is the *consumer* the
 * host is about to share the key with, not a machine on the host's LAN.
 */
export function ApiKeyRevealModal({
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
      // Clipboard may be unavailable — user can still select manually.
    }
  }

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="lg"
      ariaLabel="API-Key revealed"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-gold">
            API-Key — shown once
          </h2>
        </div>
        <div className="space-y-4 px-5 py-4">
          <p className="text-[13px] text-amber-300">
            Share this out-of-band with the person you're inviting. It will
            not be shown again.
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
            Done
          </button>
        </div>
      </div>
    </Sheet>
  )
}
