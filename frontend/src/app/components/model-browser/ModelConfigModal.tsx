import { useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'
import { llmApi } from '../../../core/api/llm'
import type { EnrichedModelDto, SetUserModelConfigRequest } from '../../../core/types/llm'

interface ModelConfigModalProps {
  model: EnrichedModelDto
  onClose: () => void
  onSaved: (model: EnrichedModelDto) => void
}

function toNullIfEmpty(s: string): string | null {
  const trimmed = s.trim()
  return trimmed.length === 0 ? null : trimmed
}

function isPowerOfTwo(n: number): boolean {
  return n > 0 && (n & (n - 1)) === 0
}

/**
 * Per-user model configuration modal. Saves via the connection-scoped
 * user-config endpoint; the path is derived from the model's
 * connection_id + model_id.
 */
export function ModelConfigModal({ model, onClose, onSaved }: ModelConfigModalProps) {
  const cfg = model.user_config
  const [isFavourite, setIsFavourite] = useState(cfg?.is_favourite ?? false)
  const [isHidden, setIsHidden] = useState(cfg?.is_hidden ?? false)
  const [customDisplayName, setCustomDisplayName] = useState(cfg?.custom_display_name ?? '')
  const [customContextWindow, setCustomContextWindow] = useState<number | null>(
    cfg?.custom_context_window ?? null,
  )
  const [notes, setNotes] = useState(cfg?.notes ?? '')
  const [systemPromptAddition, setSystemPromptAddition] = useState(
    cfg?.system_prompt_addition ?? '',
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const modelMax = model.context_window ?? 0
  const sliderDisabled = modelMax <= 80_000
  const step = isPowerOfTwo(modelMax) ? 4096 : 4000
  const displayValue = customContextWindow ?? modelMax

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const body: SetUserModelConfigRequest = {
        is_favourite: isFavourite,
        is_hidden: isHidden,
        custom_display_name: toNullIfEmpty(customDisplayName),
        custom_context_window: customContextWindow,
        notes: toNullIfEmpty(notes),
        system_prompt_addition: toNullIfEmpty(systemPromptAddition),
      }
      await llmApi.setUserModelConfig(model.connection_id, model.model_id, body)
      onSaved(model)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.')
    } finally {
      setSaving(false)
    }
  }

  async function handleReset() {
    if (!cfg) { onClose(); return }
    if (!window.confirm('Reset all personal settings for this model?')) return
    setSaving(true)
    setError(null)
    try {
      await llmApi.deleteUserModelConfig(model.connection_id, model.model_id)
      onSaved(model)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet isOpen onClose={onClose} size="lg" ariaLabel={`Configuration for ${model.display_name}`} className="bg-surface p-5 space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-lg text-white/90">{model.display_name}</h3>
          <p className="text-[11px] font-mono text-white/40">{model.unique_id}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 text-white/50 hover:bg-white/5 hover:text-white/80"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setIsFavourite(!isFavourite)}
          aria-pressed={isFavourite}
          className={[
            'inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] border transition-colors',
            isFavourite
              ? 'bg-gold/20 border-gold/60 text-gold'
              : 'bg-white/5 border-white/15 text-white/60 hover:text-white/80',
          ].join(' ')}
        >
          <span className="text-[14px]">{isFavourite ? '★' : '☆'}</span>
          <span>Favourite</span>
        </button>

        <button
          type="button"
          onClick={() => setIsHidden(!isHidden)}
          aria-pressed={!isHidden}
          className={[
            'inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] border transition-colors',
            !isHidden
              ? 'bg-emerald-500/15 border-emerald-400/60 text-emerald-300'
              : 'bg-white/5 border-white/15 text-white/60 hover:text-white/80',
          ].join(' ')}
        >
          <span className="text-[14px]">{isHidden ? '⦸' : '👁'}</span>
          <span>{isHidden ? 'Hidden' : 'Visible'}</span>
        </button>
      </div>

      <label className="flex flex-col gap-1 text-[12px] text-white/70">
        Custom display name
        <input
          type="text"
          value={customDisplayName}
          onChange={(e) => setCustomDisplayName(e.target.value)}
          placeholder={model.display_name}
          className="rounded bg-white/5 border border-white/10 px-3 py-1.5 text-[13px] text-white/85 placeholder:text-white/30 outline-none focus:border-white/25"
        />
      </label>

      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-mono uppercase tracking-wider text-white/50">
            Custom context window
          </label>
          <span className="font-mono text-[13px] text-gold">
            {displayValue.toLocaleString()} tokens
            {customContextWindow === null && <span className="text-white/40"> (model default)</span>}
          </span>
        </div>

        <input
          type="range"
          min={80_000}
          max={modelMax}
          step={step}
          value={customContextWindow ?? modelMax}
          onChange={(e) => setCustomContextWindow(Number(e.target.value))}
          disabled={sliderDisabled}
          className="w-full accent-gold disabled:opacity-30"
        />

        <div className="flex items-center justify-between text-[10px] font-mono text-white/40">
          <span>80k min</span>
          <button
            type="button"
            onClick={() => setCustomContextWindow(null)}
            className="text-white/50 hover:text-white/80 underline font-sans text-[11px]"
          >
            Use model default
          </button>
          <span>{modelMax.toLocaleString()} max</span>
        </div>

        {sliderDisabled && (
          <p className="text-[10px] text-white/40 mt-1">
            Model max ≤ 80k — context cannot be narrowed further.
          </p>
        )}
      </div>

      <label className="flex flex-col gap-1 text-[12px] text-white/70">
        Notes
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="rounded bg-white/5 border border-white/10 px-3 py-2 text-[13px] text-white/85 outline-none focus:border-white/25 resize-y"
        />
      </label>

      <label className="flex flex-col gap-1 text-[12px] text-white/70">
        System prompt addition
        <textarea
          value={systemPromptAddition}
          onChange={(e) => setSystemPromptAddition(e.target.value)}
          rows={4}
          placeholder="Appended to the persona's system prompt."
          className="rounded bg-white/5 border border-white/10 px-3 py-2 text-[13px] text-white/85 placeholder:text-white/30 outline-none focus:border-white/25 resize-y"
        />
      </label>

      {error && <div className="text-[12px] text-red-300">{error}</div>}

      <div className="flex items-center justify-between gap-2 pt-2">
        <button
          type="button"
          onClick={handleReset}
          disabled={saving || !cfg}
          className="rounded border border-red-500/30 px-3 py-1 text-[12px] text-red-300 hover:bg-red-500/10 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Reset
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded bg-purple/70 px-3 py-1 text-[12px] text-white hover:bg-purple/80 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
