import { useEffect, useId, useState } from 'react'
import { llmApi } from '../../../core/api/llm'
import { personasApi } from '../../../core/api/personas'
import { useAvatarSrc } from '../../../core/hooks/useAvatarSrc'
import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import type { ChakraColour, ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { ModelSelectionModal } from '../model-browser/ModelSelectionModal'
import { AvatarCropModal } from '../avatar-crop/AvatarCropModal'

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
  const [canReason, setCanReason] = useState(false)
  const [canUseTools, setCanUseTools] = useState(true)

  const [modelModalOpen, setModelModalOpen] = useState(false)
  const [cropOpen, setCropOpen] = useState(false)

  const avatarSrc = useAvatarSrc(persona.id, !!persona.profile_image, persona.updated_at)

  const nameId = useId()
  const taglineId = useId()
  const modelId = useId()
  const colourId = useId()
  const systemPromptId = useId()
  const temperatureId = useId()

  // Load actual model capabilities when editing an existing persona
  useEffect(() => {
    const uid = persona.model_unique_id
    if (!uid || !uid.includes(':')) return
    const providerId = uid.split(':')[0]
    const modelSlug = uid.split(':').slice(1).join(':')
    llmApi.listModels(providerId)
      .then((models) => {
        const model = models.find((m) => m.model_id === modelSlug)
        setCanReason(model?.supports_reasoning ?? false)
        setCanUseTools(model?.supports_tool_calls ?? false)
        if (model && !model.supports_reasoning) {
          setReasoningEnabled(false)
        }
      })
      .catch(() => {
        setCanReason(false)
        setCanUseTools(true)
      })
  }, [persona.model_unique_id])

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
    supports_tool_calls: boolean
  }) {
    setModelUniqueId(model.unique_id)
    setModelDisplayName(model.display_name)
    setModelProvider(model.provider_id)
    setCanReason(model.supports_reasoning)
    setCanUseTools(model.supports_tool_calls)
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
        {/* Profile picture */}
        {!isCreating && (
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={() => setCropOpen(true)}
              className="group relative rounded-full flex-shrink-0 cursor-pointer"
              aria-label="Change profile picture"
              title="Change profile picture"
              style={{
                width: 64,
                height: 64,
                background: avatarSrc ? undefined : `${chakra.hex}22`,
                border: `2px solid ${chakra.hex}44`,
              }}
            >
              {avatarSrc ? (
                <CroppedAvatar
                  personaId={persona.id}
                  updatedAt={persona.updated_at}
                  crop={persona.profile_crop}
                  size={60}
                  alt={persona.name}
                />
              ) : (
                <span
                  className="flex items-center justify-center w-full h-full text-xl font-bold select-none rounded-full"
                  style={{ color: chakra.hex }}
                >
                  {persona.monogram}
                </span>
              )}
              <div className="absolute inset-0 rounded-full bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-80">
                  <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                  <circle cx="12" cy="13" r="4" />
                </svg>
              </div>
            </button>
            <div className="flex flex-col gap-0.5">
              <span className="text-[11px] text-white/40 uppercase tracking-wider">Profile picture</span>
              <span className="text-[11px] text-white/60">Click to {persona.profile_image ? 'change' : 'add'}</span>
            </div>
          </div>
        )}

        {/* Name */}
        <label className="flex flex-col gap-1.5" htmlFor={nameId}>
          <span className="text-[11px] text-white/40 uppercase tracking-wider">Name</span>
          <input
            id={nameId}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={inputStyle}
            onFocus={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}66` }}
            onBlur={(e) => { e.currentTarget.style.borderColor = `${chakra.hex}26` }}
          />
        </label>

        {/* Tagline */}
        <label className="flex flex-col gap-1.5" htmlFor={taglineId}>
          <span className="text-[11px] text-white/40 uppercase tracking-wider">Tagline</span>
          <input
            id={taglineId}
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
          <label htmlFor={modelId} className="text-[11px] text-white/40 uppercase tracking-wider">Model</label>
          <button
            id={modelId}
            type="button"
            aria-label="Select model"
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
              <span className="text-[13px] text-white/60 italic">Select a model...</span>
            )}
          </button>
          {modelUniqueId && !canUseTools && (
            <div
              className="mt-1.5 flex items-center gap-1.5 rounded px-2 py-1 text-[11px]"
              style={{
                background: 'rgba(250, 179, 135, 0.08)',
                border: '1px solid rgba(250, 179, 135, 0.2)',
                color: 'rgba(250, 179, 135, 0.85)',
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              This model does not support tool calls (web search, etc.)
            </div>
          )}
        </div>

        {/* Chakra colour picker */}
        <div className="flex flex-col gap-2">
          <span id={colourId} className="text-[11px] text-white/40 uppercase tracking-wider">Chakra colour</span>
          <div className="flex gap-2 flex-wrap" role="radiogroup" aria-labelledby={colourId}>
            {CHAKRA_COLOURS.map((c) => {
              const entry = CHAKRA_PALETTE[c]
              const isSelected = colourScheme === c
              return (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={isSelected}
                  aria-label={entry.label}
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
        <label className="flex flex-col gap-1.5" htmlFor={systemPromptId}>
          <span className="text-[11px] text-white/40 uppercase tracking-wider">System prompt</span>
          <textarea
            id={systemPromptId}
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
            <label htmlFor={temperatureId} className="text-[11px] text-white/40 uppercase tracking-wider">Temperature</label>
            <span className="text-[12px] text-white/60 font-mono">{temperature.toFixed(2)}</span>
          </div>
          <input
            id={temperatureId}
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={temperature}
            onChange={(e) => setTemperature(parseFloat(e.target.value))}
            className="w-full cursor-pointer"
            style={{ accentColor: chakra.hex }}
          />
          <div className="flex justify-between text-[10px] text-white/60">
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

      {cropOpen && !isCreating && (
        <AvatarCropModal
          isOpen={cropOpen}
          onClose={() => setCropOpen(false)}
          onSave={async (blob, crop) => {
            if (blob) {
              await personasApi.uploadAvatar(persona.id, blob, crop)
            } else {
              await personasApi.updateAvatarCrop(persona.id, crop)
            }
            setCropOpen(false)
          }}
          onRemove={async () => {
            await personasApi.deleteAvatar(persona.id)
            setCropOpen(false)
          }}
          hasExisting={!!persona.profile_image}
          currentImageUrl={avatarSrc}
          initialCrop={persona.profile_crop}
          accentColour={chakra.hex}
        />
      )}

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
    <button
      type="button"
      className="flex items-center justify-between py-2 px-3 rounded-lg w-full text-left"
      role="switch"
      aria-checked={value}
      aria-label={label}
      aria-describedby={undefined}
      disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.05)',
        opacity: disabled ? 0.3 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
      title={disabled ? description : undefined}
      onClick={() => !disabled && onChange(!value)}
      onKeyDown={(e) => {
        if (!disabled && (e.key === ' ' || e.key === 'Enter')) {
          e.preventDefault()
          onChange(!value)
        }
      }}
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-[13px] text-white/75">{label}</span>
        <span className="text-[11px] text-white/60">{description}</span>
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
    </button>
  )
}
