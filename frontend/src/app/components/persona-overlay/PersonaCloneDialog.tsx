import { useEffect, useRef, useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'
import { personasApi } from '../../../core/api/personas'
import type { PersonaDto } from '../../../core/types/persona'

interface PersonaCloneDialogProps {
  source: PersonaDto
  onClose: () => void
  onCloned: (clone: PersonaDto) => void
}

export function PersonaCloneDialog({ source, onClose, onCloned }: PersonaCloneDialogProps) {
  const [name, setName] = useState(`${source.name} Clone`)
  const [cloneMemory, setCloneMemory] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const clone = await personasApi.clonePersona(source.id, {
        name: name.trim(),
        clone_memory: cloneMemory,
      })
      onCloned(clone)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clone failed')
      setSubmitting(false)
    }
  }

  return (
    <Sheet isOpen onClose={onClose} size="sm" ariaLabel="Clone persona">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
        <header className="flex items-center justify-between">
          <h3 className="text-[15px] font-semibold text-white/85">Clone persona</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 text-white/50 hover:bg-white/5 hover:text-white/80"
          >
            ✕
          </button>
        </header>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-white/60">Name</span>
          <input
            ref={inputRef}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded border border-white/10 bg-black/20 px-3 py-2 text-[13px] text-white/85 focus:border-white/25 focus:outline-none"
            placeholder={`${source.name} Clone`}
          />
        </label>

        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={cloneMemory}
            onChange={(e) => setCloneMemory(e.target.checked)}
            className="mt-1"
          />
          <span className="flex flex-col">
            <span className="text-[13px] text-white/85">Clone memories</span>
            <span className="text-[11px] text-white/50">
              Carry journal entries and consolidated memories over from the source persona. History is never cloned.
            </span>
          </span>
        </label>

        {error && (
          <p className="text-[12px] text-red-300">{error}</p>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded px-3 py-1.5 text-[12px] text-white/70 hover:bg-white/5 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded border border-gold/40 bg-gold/10 px-4 py-1.5 text-[12px] text-gold transition-colors hover:bg-gold/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Cloning…' : 'Clone'}
          </button>
        </div>
      </form>
    </Sheet>
  )
}
