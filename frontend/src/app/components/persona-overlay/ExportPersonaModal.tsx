import { useId, useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'

interface ExportPersonaModalProps {
  personaName: string
  chakraHex: string
  busy: boolean
  onCancel: () => void
  onExport: (includeContent: boolean) => void | Promise<void>
}

/**
 * Compact modal that asks the user whether to include memory/artefacts/
 * uploads alongside the always-included personality + chat history when
 * exporting a persona.
 */
export function ExportPersonaModal({
  personaName,
  chakraHex,
  busy,
  onCancel,
  onExport,
}: ExportPersonaModalProps) {
  const [includeContent, setIncludeContent] = useState(false)
  const titleId = useId()
  const checkboxId = useId()

  return (
    <Sheet
      isOpen={true}
      onClose={busy ? () => {} : onCancel}
      size="md"
      ariaLabel={`Export persona ${personaName}`}
      className="border border-white/8 bg-elevated shadow-2xl"
    >
      <div className="flex flex-col">
        {/* Header */}
        <div className="border-b border-white/6 px-5 py-4">
          <h2
            id={titleId}
            className="text-[13px] font-mono uppercase tracking-wider text-white/60"
          >
            Export Persona
          </h2>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-4 px-5 py-4">
          <p className="text-[12px] leading-relaxed text-white/70">
            Export includes personality (system prompt, nsfw flag) and chat
            history. Enable &ldquo;Include content&rdquo; to also include
            memory, artefacts, and uploads.
          </p>

          <label
            htmlFor={checkboxId}
            className="flex cursor-pointer items-center gap-3"
          >
            <input
              id={checkboxId}
              type="checkbox"
              checked={includeContent}
              onChange={(e) => setIncludeContent(e.target.checked)}
              disabled={busy}
              className="h-3.5 w-3.5 cursor-pointer"
              style={{ accentColor: chakraHex }}
            />
            <span className="text-[12px] text-white/75">
              Include content (memory, artefacts, uploads)
            </span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-white/6 px-5 py-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded border border-white/8 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/60 transition-colors hover:border-white/15 hover:text-white/80 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onExport(includeContent)}
            disabled={busy}
            className="rounded px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
            style={{
              background: `${chakraHex}22`,
              border: `1px solid ${chakraHex}66`,
              color: chakraHex,
            }}
          >
            {busy ? 'Exporting…' : 'Export'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
