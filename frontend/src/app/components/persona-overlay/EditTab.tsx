import { useState } from 'react'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import type { ChakraColour, ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { ModelSelectionModal } from '../model-browser/ModelSelectionModal'

interface EditTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
  isCreating?: boolean
}

const CHAKRA_COLOURS: ChakraColour[] = ['root', 'sacral', 'solar', 'heart', 'throat', 'third_eye', 'crown']

export function EditTab({ persona, chakra, onSave, isCreating }: EditTabProps) {
  const [name, setName] = useState(persona.name)
  const [tagline, setTagline] = useState(persona.tagline)
  const [colourScheme, setColourScheme] = useState<ChakraColour>(persona.colour_scheme)
  const [systemPrompt, setSystemPrompt] = useState(persona.system_prompt)
  const [temperature, setTemperature] = useState(persona.temperature)
  const [reasoningEnabled, setReasoningEnabled] = useState(persona.reasoning_enabled)
  const [nsfw, setNsfw] = useState(persona.nsfw)
  const [saving, setSaving] = useState(false)
  const [modelUniqueId, setModelUniqueId] = useState(persona.model_unique_id)
  const [modelDisplayName, setModelDisplayName] = useState(
    persona.model_unique_id ? persona.model_unique_id.split(':').slice(1).join(':') : ''
  )
  const [modelProvider, setModelProvider] = useState(
    persona.model_unique_id ? persona.model_unique_id.split(':')[0] : ''
  )
  const [canReason, setCanReason] = useState(persona.model_unique_id !== '')

  const [modelModalOpen, setModelModalOpen] = useState(false)

  const isDirty = isCreating ||
    name !== persona.name ||
    tagline !== persona.tagline ||
    colourScheme !== persona.colour_scheme ||
    systemPrompt !== persona.system_prompt ||
    temperature !== persona.temperature ||
    reasoningEnabled !== persona.reasoning_enabled ||
    nsfw !== persona.nsfw ||
    modelUniqueId !== persona.model_unique_id

  const canSave = isCreating
    ? name.trim() !== '' && tagline.trim() !== '' && modelUniqueId !== ''
    : isDirty

  async function handleSave() {
    if (!canSave || saving) return
    setSaving(true)
    try {
      const data: Record<string, unknown> = {
        name,
        tagline,
        colour_scheme: colourScheme,
        system_prompt: systemPrompt,
        temperature,
        reasoning_enabled: reasoningEnabled,
        nsfw,
        model_unique_id: modelUniqueId,
      }
      await onSave(isCreating ? null : persona.id, data)
    } finally {
      setSaving(false)
    }
  }

  function handleModelSelect(model: {
    unique_id: string
    display_name: string
    provider_id: string
    supports_reasoning: boolean
  }) {
    setModelUniqueId(model.unique_id)
    setModelDisplayName(model.display_name)
    setModelProvider(model.provider_id)
    setCanReason(model.supports_reasoning)
    if (!model.supports_reasoning) {
      setReasoningEnabled(false)
    }
    setModelModalOpen(false)
  }

  const inputStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.03)',
    border: `1px solid ${chakra.hex}26`,
    borderRadius: 8,
    color: 'rgba(255,255,255,0.85)',
    fontSize: 13,
    padding: '8px 12px',
    outline: 'none',
    width: '100%',
    transition: 'border-color 0.15s',
  }

  return (
    <>
      <div className="flex flex-col gap-5 px-6 py-6 max-w-lg mx-auto w-full">
        {/* Name */}
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] text-white/40 uppercase tracking-wider">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={inputStyle}
            onFocus={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}66` }}
            onBlur={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}26` }}
          />
        </label>

        {/* Tagline */}
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] text-white/40 uppercase tracking-wider">Tagline</span>
          <input
            type="text"
            value={tagline}
            onChange={(e) => setTagline(e.target.value)}
            style={inputStyle}
            onFocus={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}66` }}
            onBlur={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}26` }}
          />
        </label>

        {/* Model */}
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] text-white/40 uppercase tracking-wider">Model</span>
          <button
            type="button"
            onClick={() => setModelModalOpen(true)}
            className="flex items-center gap-2 w-full text-left rounded-lg px-3 py-2.5 transition-colors hover:bg-white/4 cursor-pointer"
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: modelUniqueId
                ? `1px solid ${chakra.hex}26`
                : '1px solid rgba(243, 139, 168, 0.4)',
              borderRadius: 8,
            }}
          >
            {modelUniqueId ? (
              <>
                <span className="text-[10px] font-mono text-white/35 uppercase tracking-wider">{modelProvider}</span>
                <span className="text-[13px] text-white/80">{modelDisplayName || modelUniqueId}</span>
              </>
            ) : (
              <span className="text-[13px] text-white/30 italic">Select a model...</span>
            )}
          </button>
        </div>

        {/* Chakra colour picker */}
        <div className="flex flex-col gap-2">
          <span className="text-[11px] text-white/40 uppercase tracking-wider">Chakra colour</span>
          <div className="flex gap-2 flex-wrap">
            {CHAKRA_COLOURS.map((c) => {
              const entry = CHAKRA_PALETTE[c]
              const isSelected = colourScheme === c
              return (
                <button
                  key={c}
                  type="button"
                  title={entry.label}
                  onClick={() => setColourScheme(c)}
                  className="transition-transform hover:scale-110"
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: '50%',
                    background: entry.hex,
                    border: isSelected ? `2px solid white` : '2px solid transparent',
                    outline: isSelected ? `2px solid ${entry.hex}` : 'none',
                    cursor: 'pointer',
                    flexShrink: 0,
                  }}
                />
              )
            })}
          </div>
        </div>

        {/* System prompt */}
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] text-white/40 uppercase tracking-wider">System prompt</span>
          <textarea
            value={systemPrompt}
            onChange={(e) => {
              setSystemPrompt(e.target.value)
              // Auto-grow
              e.currentTarget.style.height = 'auto'
              e.currentTarget.style.height = `${e.currentTarget.scrollHeight}px`
            }}
            rows={5}
            style={{
              ...inputStyle,
              resize: 'none',
              lineHeight: '1.5',
              overflowY: 'hidden',
            }}
            onFocus={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}66` }}
            onBlur={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}26` }}
          />
        </label>

        {/* Temperature */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-white/40 uppercase tracking-wider">Temperature</span>
            <span className="text-[12px] text-white/60 font-mono">{temperature.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={temperature}
            onChange={(e) => setTemperature(parseFloat(e.target.value))}
            className="w-full cursor-pointer"
            style={{ accentColor: chakra.hex }}
          />
          <div className="flex justify-between text-[10px] text-white/25">
            <span>Precise</span>
            <span>Creative</span>
          </div>
        </div>

        {/* Toggles */}
        <div className="flex flex-col gap-3">
          <Toggle
            label="Reasoning"
            description={canReason ? "Enable extended thinking for complex tasks" : "Model does not support reasoning"}
            value={reasoningEnabled}
            onChange={setReasoningEnabled}
            chakraHex={chakra.hex}
            disabled={!canReason}
          />
          <Toggle
            label="NSFW"
            description="Hide this persona and related data in 'sanitised' mode"
            value={nsfw}
            onChange={setNsfw}
            chakraHex={chakra.hex}
          />
        </div>

        {/* Save button */}
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave || saving}
          className="mt-2 py-2 px-6 rounded-lg text-[13px] font-semibold transition-all self-end"
          style={{
            background: canSave && !saving ? chakra.hex : 'rgba(255,255,255,0.06)',
            color: canSave && !saving ? '#0f0d16' : 'rgba(255,255,255,0.25)',
            cursor: canSave && !saving ? 'pointer' : 'not-allowed',
            border: 'none',
          }}
        >
          {saving ? 'Saving…' : isCreating ? 'Create' : 'Save'}
        </button>
      </div>

      {modelModalOpen && (
        <ModelSelectionModal
          currentModelId={modelUniqueId || null}
          onSelect={handleModelSelect}
          onClose={() => setModelModalOpen(false)}
        />
      )}
    </>
  )
}

interface ToggleProps {
  label: string
  description: string
  value: boolean
  onChange: (v: boolean) => void
  chakraHex: string
  disabled?: boolean
}

function Toggle({ label, description, value, onChange, chakraHex, disabled }: ToggleProps) {
  return (
    <div
      className="flex items-center justify-between py-2 px-3 rounded-lg"
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.05)',
        opacity: disabled ? 0.3 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
      title={disabled ? description : undefined}
      onClick={() => !disabled && onChange(!value)}
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-[13px] text-white/75">{label}</span>
        <span className="text-[11px] text-white/30">{description}</span>
      </div>

      {/* Custom toggle — 44×20px */}
      <div
        className="relative flex-shrink-0"
        style={{
          width: 44,
          height: 20,
          borderRadius: 10,
          background: value ? `${chakraHex}cc` : 'rgba(255,255,255,0.12)',
          transition: 'background 0.2s',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 2,
            left: 2,
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: 'white',
            transform: value ? 'translateX(24px)' : 'translateX(0)',
            transition: 'transform 0.2s',
            boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
          }}
        />
      </div>
    </div>
  )
}
