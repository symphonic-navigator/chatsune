import { useState, useEffect, useRef, useId } from "react"
import type { EnrichedModelDto, SetUserModelConfigRequest } from "../../../core/types/llm"
import { llmApi } from "../../../core/api/llm"
import { slugWithoutProvider } from "./modelFilters"
import { useFocusTrap } from "../../hooks/useFocusTrap"

const SYSTEM_PROMPT_LIMIT = 4000
const NOTES_LIMIT = 2000
const DISPLAY_NAME_LIMIT = 100
const MIN_CONTEXT_FOR_SLIDER = 96_000

const CONTEXT_STEPS: number[] = [
  96_000, 128_000, 160_000, 192_000, 224_000, 256_000,
  384_000, 512_000,
  768_000, 1_000_000, 1_250_000, 1_500_000, 2_000_000,
]

function availableSteps(maxContext: number): number[] {
  const steps = CONTEXT_STEPS.filter((s) => s <= maxContext)
  if (steps.length === 0 || steps[steps.length - 1] !== maxContext) {
    steps.push(maxContext)
  }
  return steps
}

function formatContextLabel(ctx: number): string {
  if (ctx >= 1_000_000) {
    const val = ctx / 1_000_000
    return val % 1 === 0 ? `${val}M` : `${val.toFixed(2).replace(/0+$/, "").replace(/\.$/, "")}M`
  }
  return `${Math.round(ctx / 1_000)}k`
}

function autoGrow(el: HTMLTextAreaElement) {
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, 12 * 24)}px`
}

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
  const [isHidden, setIsHidden] = useState(model.user_config?.is_hidden ?? false)
  const [customDisplayName, setCustomDisplayName] = useState(
    model.user_config?.custom_display_name ?? "",
  )
  const [customContextWindow, setCustomContextWindow] = useState<number | null>(
    model.user_config?.custom_context_window ?? null,
  )
  const backdropRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useFocusTrap(dialogRef, true)

  const contextSliderAvailable = model.context_window >= MIN_CONTEXT_FOR_SLIDER
  const steps = contextSliderAvailable ? availableSteps(model.context_window) : []
  const effectiveContext = customContextWindow ?? model.context_window
  const stepIndex = steps.length > 0
    ? steps.reduce((closest, s, i) =>
        Math.abs(s - effectiveContext) < Math.abs(steps[closest] - effectiveContext) ? i : closest, 0)
    : 0

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
        is_hidden: isHidden,
        custom_display_name: customDisplayName.trim() || null,
        custom_context_window: contextSliderAvailable && customContextWindow !== null && customContextWindow !== model.context_window
          ? customContextWindow
          : null,
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
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full sm:max-w-lg rounded-xl border border-white/8 bg-surface shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <div className="min-w-0 flex-1">
            <div id={titleId} className="truncate text-[13px] font-semibold text-white/80">
              {model.display_name}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/40">
              <span>{model.provider_display_name}</span>
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
              <div className="text-[10px] text-white/60">
                Favourited models appear at the top of the selection list
              </div>
            </div>
          </label>

          {/* Hidden toggle */}
          <div
            className="flex items-center gap-3 cursor-pointer py-2"
            onClick={() => setIsHidden(!isHidden)}
          >
            <div
              className={[
                "relative h-[18px] w-[32px] flex-shrink-0 rounded-full transition-colors",
                isHidden ? "bg-[#f38ba8]" : "bg-white/15",
              ].join(" ")}
            >
              <div
                className={[
                  "absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white transition-all",
                  isHidden ? "left-[16px]" : "left-[2px]",
                ].join(" ")}
              />
            </div>
            <div>
              <div className="text-[12px] text-white/70">Hidden</div>
              <div className="text-[10px] text-white/60">
                Hide this model from your model selection lists
              </div>
            </div>
          </div>

          {/* Custom Display Name */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label
                htmlFor="config-display-name"
                className="block text-[11px] font-medium uppercase tracking-wider text-white/40"
              >
                Custom Display Name
              </label>
              <span className={[
                "text-[10px]",
                customDisplayName.length > DISPLAY_NAME_LIMIT * 0.9
                  ? "text-[#f38ba8]"
                  : "text-white/20",
              ].join(" ")}>
                {customDisplayName.length}/{DISPLAY_NAME_LIMIT}
              </span>
            </div>
            <input
              id="config-display-name"
              type="text"
              value={customDisplayName}
              onChange={(e) => {
                if (e.target.value.length <= DISPLAY_NAME_LIMIT) {
                  setCustomDisplayName(e.target.value)
                }
              }}
              placeholder="Leave empty to use default name"
              className="w-full rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
            />
            {model.display_name && (
              <div className="mt-1 text-[10px] text-white/60">
                Original: {model.display_name}
              </div>
            )}
          </div>

          {/* Context Size */}
          {contextSliderAvailable ? (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="block text-[11px] font-medium uppercase tracking-wider text-white/40">
                  Context Size
                </label>
                <span className="text-[12px] font-semibold text-gold">
                  {formatContextLabel(steps[stepIndex])}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={steps.length - 1}
                value={stepIndex}
                onChange={(e) => {
                  const idx = parseInt(e.target.value, 10)
                  const value = steps[idx]
                  setCustomContextWindow(value === model.context_window ? null : value)
                }}
                className="w-full accent-[#f9e2af]"
              />
              <div className="mt-1 flex justify-between text-[9px] text-white/20">
                <span>{formatContextLabel(steps[0])}</span>
                <span className={effectiveContext === model.context_window ? "text-white/50 font-semibold" : ""}>
                  {formatContextLabel(model.context_window)} (max)
                </span>
              </div>
              <div className="mt-1.5 text-[10px] text-white/60">
                Smaller context = lower cost per message. Default is the model's maximum.
              </div>
            </div>
          ) : (
            <div>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-white/60">
                Context Size
              </div>
              <div className="text-[10px] text-white/60 italic">
                Context adjustment available for models with 96k+ context window.
                This model has {formatContextLabel(model.context_window)}.
              </div>
            </div>
          )}

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
              onInput={(e) => autoGrow(e.currentTarget)}
              style={{ maxHeight: `${12 * 24}px` }}
              placeholder="Additional instructions appended to the system prompt when this model is used"
              rows={4}
              className="w-full resize-none overflow-y-auto rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
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
              onInput={(e) => autoGrow(e.currentTarget)}
              style={{ maxHeight: `${12 * 24}px` }}
              placeholder="Personal notes about this model (only visible to you)"
              rows={3}
              className="w-full resize-none overflow-y-auto rounded-lg border border-white/8 bg-elevated px-3 py-2 text-[12px] text-white/80 placeholder-white/20 outline-none focus:border-gold/40 transition-colors"
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
