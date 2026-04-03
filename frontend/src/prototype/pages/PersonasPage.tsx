import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { usePersonas } from "../../core/hooks/usePersonas"
import type { PersonaDto, CreatePersonaRequest, UpdatePersonaRequest } from "../../core/types/persona"

function PersonaForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial?: Partial<PersonaDto>
  onSubmit: (data: CreatePersonaRequest | UpdatePersonaRequest) => Promise<void>
  onCancel: () => void
  submitLabel: string
}) {
  const [name, setName] = useState(initial?.name ?? "")
  const [tagline, setTagline] = useState(initial?.tagline ?? "")
  const [modelUniqueId, setModelUniqueId] = useState(initial?.model_unique_id ?? "")
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt ?? "")
  const [temperature, setTemperature] = useState(initial?.temperature ?? 0.8)
  const [reasoningEnabled, setReasoningEnabled] = useState(initial?.reasoning_enabled ?? false)
  const [colourScheme, setColourScheme] = useState(initial?.colour_scheme ?? "")
  const [displayOrder, setDisplayOrder] = useState(initial?.display_order ?? 0)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await onSubmit({
        name,
        tagline,
        model_unique_id: modelUniqueId,
        system_prompt: systemPrompt,
        temperature,
        reasoning_enabled: reasoningEnabled,
        colour_scheme: colourScheme,
        display_order: displayOrder,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operation failed")
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Name</label>
          <input
            type="text" value={name} onChange={(e) => setName(e.target.value)} required
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Tagline</label>
          <input
            type="text" value={tagline} onChange={(e) => setTagline(e.target.value)} required
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Model ID</label>
          <input
            type="text" value={modelUniqueId} onChange={(e) => setModelUniqueId(e.target.value)} required
            placeholder="provider:model_slug"
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Colour Scheme</label>
          <input
            type="text" value={colourScheme} onChange={(e) => setColourScheme(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Temperature ({temperature})</label>
          <input
            type="range" min="0" max="2" step="0.1" value={temperature}
            onChange={(e) => setTemperature(parseFloat(e.target.value))}
            className="w-full"
          />
        </div>
        <div className="flex items-center gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Display Order</label>
            <input
              type="number" value={displayOrder} onChange={(e) => setDisplayOrder(parseInt(e.target.value) || 0)}
              className="w-20 rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <label className="flex items-center gap-2 mt-4">
            <input type="checkbox" checked={reasoningEnabled} onChange={(e) => setReasoningEnabled(e.target.checked)} />
            <span className="text-sm">Reasoning</span>
          </label>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">System Prompt</label>
        <textarea
          value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} required rows={4}
          className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700">
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="rounded bg-gray-100 px-4 py-1.5 text-sm hover:bg-gray-200">
          Cancel
        </button>
      </div>
    </form>
  )
}

function PersonaCard({
  persona,
  onEdit,
  onDelete,
}: {
  persona: PersonaDto
  onEdit: (p: PersonaDto) => void
  onDelete: (id: string) => void
}) {
  const navigate = useNavigate()

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-medium text-sm">{persona.name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{persona.tagline}</p>
        </div>
        <div className="flex gap-1">
          <button onClick={() => navigate(`/chat/${persona.id}`)} className="rounded bg-green-600 px-2 py-1 text-xs text-white hover:bg-green-700">Chat</button>
          <button onClick={() => onEdit(persona)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
          <button onClick={() => onDelete(persona.id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Delete</button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-50 px-2 py-0.5">{persona.model_unique_id}</span>
        <span className="rounded bg-gray-50 px-2 py-0.5">temp: {persona.temperature}</span>
        {persona.reasoning_enabled && <span className="rounded bg-blue-50 px-2 py-0.5 text-blue-600">reasoning</span>}
        {persona.colour_scheme && <span className="rounded bg-gray-50 px-2 py-0.5">colour: {persona.colour_scheme}</span>}
        <span className="rounded bg-gray-50 px-2 py-0.5">order: {persona.display_order}</span>
      </div>
      <p className="mt-2 text-xs text-gray-400 line-clamp-2">{persona.system_prompt}</p>
    </div>
  )
}

export default function PersonasPage() {
  const { personas, isLoading, error, create, update, remove } = usePersonas()
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<PersonaDto | null>(null)

  const handleCreate = async (data: CreatePersonaRequest | UpdatePersonaRequest) => {
    await create(data as CreatePersonaRequest)
    setShowCreate(false)
  }

  const handleUpdate = async (data: CreatePersonaRequest | UpdatePersonaRequest) => {
    if (!editing) return
    await update(editing.id, data as UpdatePersonaRequest)
    setEditing(null)
  }

  const handleDelete = async (id: string) => {
    if (confirm("Delete this persona?")) {
      await remove(id)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Personas</h2>
        <button
          onClick={() => { setShowCreate(true); setEditing(null) }}
          className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          Create Persona
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {showCreate && (
        <PersonaForm onSubmit={handleCreate} onCancel={() => setShowCreate(false)} submitLabel="Create" />
      )}

      {editing && (
        <PersonaForm initial={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} submitLabel="Update" />
      )}

      {isLoading && personas.length === 0 ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : personas.length === 0 ? (
        <p className="text-sm text-gray-400">No personas yet</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {personas.map((p) => (
            <PersonaCard key={p.id} persona={p} onEdit={setEditing} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  )
}
