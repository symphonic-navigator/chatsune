import { useState, useEffect, useRef } from "react"
import type { EnrichedModelDto, SetUserModelConfigRequest } from "../../../core/types/llm"
import { llmApi } from "../../../core/api/llm"
import { slugWithoutProvider } from "./modelFilters"

const SYSTEM_PROMPT_LIMIT = 4000
const NOTES_LIMIT = 2000

interface ModelConfigModalProps {
  model: EnrichedModelDto
  onClose: () => void
  onSaved: (model: EnrichedModelDto) => void
}

export function ModelConfigModal({ model, onClose, onSaved }: ModelConfigModalProps) {
  const [isFavourite, setIsFavourite] = useState(model.user_config?.is_favourite ?? false)
  const [notes, setNotes] = useState(model.user_config?.notes ?? "")
  const [systemPromptAddition, setSystemPromptAddition] = useState(
    model.user_config?.system_prompt_addition ?? "",
  )
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
      const providerId = model.provider_id
      const modelSlug = slugWithoutProvider(model.unique_id)

      const data: SetUserModelConfigRequest = {
        is_favourite: isFavourite,
        notes: notes.trim() || null,
        system_prompt_addition: systemPromptAddition.trim() || null,
      }

      const savedConfig = await llmApi.setUserConfig(providerId, modelSlug, data)
      onSaved({ ...model, user_config: savedConfig })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save configuration")
    } finally {
      setSaving(false)
    }
  }

  const paramInfo = [model.parameter_count, model.quantisation_level].filter(Boolean).join(" ")

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
    >
      <div className="w-full max-w-lg rounded-xl border border-white/8 bg-surface shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold text-white/80">
              {model.display_name}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/40">
              <span>{model.provider_id}</span>
              <span className="text-white/20">|</span>
              <span className="font-mono text-[10px]">{model.model_id}</span>
              {paramInfo && (
                <>
                  <span className="text-white/20">|</span>
                  <span>{paramInfo}</span>
                </>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors"
          >
            &#x2715;
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 px-5 py-4">
          {/* Favourite toggle */}
          <label className="flex items-center gap-3 cursor-pointer">
            <button
              type="button"
              onClick={() => setIsFavourite(!isFavourite)}
              className={[
                "text-[18px] transition-colors cursor-pointer",
                isFavourite ? "text-gold" : "text-white/20 hover:text-white/40",
              ].join(" ")}
            >
              {isFavourite ? "\u2605" : "\u2606"}
            </button>
            <div>
              <div className="text-[12px] text-white/70">Favourite</div>
              <div className="text-[10px] text-white/30">
                Favourited models appear at the top of the selection list
              </div>
            </div>
          </label>

          {/* System Prompt Addition */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label
                htmlFor="config-system-prompt"
                className="block text-[11px] font-medium uppercase tracking-wider text-white/40"
              >
                System Prompt Addition
              </label>
              <span className={[
                "text-[10px]",
                systemPromptAddition.length > SYSTEM_PROMPT_LIMIT * 0.9
                  ? "text-[#f38ba8]"
                  : "text-white/20",
              ].join(" ")}>
                {systemPromptAddition.length}/{SYSTEM_PROMPT_LIMIT}
              </span>
            </div>
            <textarea
              id="config-system-prompt"
              value={systemPromptAddition}
              onChange={(e) => {
                if (e.target.value.length <= SYSTEM_PROMPT_LIMIT) {
                  setSystemPromptAddition(e.target.value)
                }
              }}
              placeholder="Additional instructions appended to the system prompt when this model is used"
              rows={4}
              className="w-full resize-none rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
            />
          </div>

          {/* Notes */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label
                htmlFor="config-notes"
                className="block text-[11px] font-medium uppercase tracking-wider text-white/40"
              >
                Notes
              </label>
              <span className={[
                "text-[10px]",
                notes.length > NOTES_LIMIT * 0.9
                  ? "text-[#f38ba8]"
                  : "text-white/20",
              ].join(" ")}>
                {notes.length}/{NOTES_LIMIT}
              </span>
            </div>
            <textarea
              id="config-notes"
              value={notes}
              onChange={(e) => {
                if (e.target.value.length <= NOTES_LIMIT) {
                  setNotes(e.target.value)
                }
              }}
              placeholder="Personal notes about this model (only visible to you)"
              rows={3}
              className="w-full resize-none rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
            />
          </div>

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
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  )
}
