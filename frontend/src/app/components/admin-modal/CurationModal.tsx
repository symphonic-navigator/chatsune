import { useState, useEffect, useRef } from "react"
import type { ModelMetaDto, ModelRating, SetModelCurationRequest } from "../../../core/types/llm"
import { llmApi } from "../../../core/api/llm"

interface CurationModalProps {
  model: ModelMetaDto
  onCurationSaved: (model: ModelMetaDto) => void
  onClose: () => void
}

const RATINGS: { value: ModelRating; label: string; colour: string; bgActive: string }[] = [
  { value: "recommended", label: "Recommended", colour: "text-[#a6e3a1]", bgActive: "bg-[#a6e3a1]/15 border-[#a6e3a1]/40" },
  { value: "available", label: "Available", colour: "text-[#89b4fa]", bgActive: "bg-[#89b4fa]/15 border-[#89b4fa]/40" },
  { value: "not_recommended", label: "Not Recommended", colour: "text-[#f38ba8]", bgActive: "bg-[#f38ba8]/15 border-[#f38ba8]/40" },
]

export function CurationModal({ model, onCurationSaved, onClose }: CurationModalProps) {
  const [rating, setRating] = useState<ModelRating>(model.curation?.overall_rating ?? "available")
  const [hidden, setHidden] = useState(model.curation?.hidden ?? false)
  const [description, setDescription] = useState(model.curation?.admin_description ?? "")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === backdropRef.current) onClose()
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const data: SetModelCurationRequest = {
        overall_rating: rating,
        hidden,
        admin_description: description.trim() || null,
      }
      const curation = await llmApi.setCuration(model.provider_id, model.model_id, data)
      onCurationSaved({ ...model, curation })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save curation")
    } finally {
      setSaving(false)
    }
  }

  // Format parameter info for the header
  const paramInfo = [model.parameter_count, model.quantisation_level].filter(Boolean).join(" ")

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
    >
      <div className="w-full max-w-md rounded-xl border border-white/8 bg-surface shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold text-white/80">
              {model.display_name}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/40">
              <span>{model.provider_display_name}</span>
              {paramInfo && (
                <>
                  <span className="text-white/20">|</span>
                  <span>{paramInfo}</span>
                </>
              )}
              <span className="text-white/20">|</span>
              <span>{(model.context_window / 1024).toFixed(0)}k ctx</span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          {/* Rating selection */}
          <div>
            <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-white/40">
              Rating
            </label>
            <div className="flex gap-2">
              {RATINGS.map((r) => (
                <button
                  key={r.value}
                  type="button"
                  onClick={() => setRating(r.value)}
                  className={[
                    "flex-1 rounded-lg border px-3 py-2 text-[12px] font-medium transition-colors cursor-pointer",
                    rating === r.value
                      ? `${r.bgActive} ${r.colour}`
                      : "border-white/8 text-white/40 hover:border-white/15 hover:text-white/60",
                  ].join(" ")}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {/* Admin description */}
          <div>
            <label
              htmlFor="curation-description"
              className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-white/40"
            >
              Admin Description
            </label>
            <textarea
              id="curation-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional note visible to users (e.g. best for creative writing)"
              rows={3}
              className="w-full resize-none rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
            />
          </div>

          {/* Hidden toggle */}
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={hidden}
              onChange={(e) => setHidden(e.target.checked)}
              className="h-4 w-4 rounded border-white/20 bg-elevated accent-gold"
            />
            <div>
              <div className="text-[12px] text-white/70">Hidden</div>
              <div className="text-[10px] text-white/30">
                Hidden models are not shown to regular users
              </div>
            </div>
          </label>

          {/* Error message */}
          {error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-400">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-white/6 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-4 py-2 text-[12px] text-white/55 hover:bg-white/6 hover:text-white/75 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-gold/15 border border-gold/30 px-4 py-2 text-[12px] font-medium text-gold hover:bg-gold/25 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {saving ? "Saving..." : "Save Curation"}
          </button>
        </div>
      </div>
    </div>
  )
}
