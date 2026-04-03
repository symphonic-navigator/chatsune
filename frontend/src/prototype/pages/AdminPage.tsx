import { useState } from "react"
import { useSettings } from "../../core/hooks/useSettings"
import { useLlm } from "../../core/hooks/useLlm"
import type { ModelMetaDto, ModelRating } from "../../core/types/llm"

type Tab = "settings" | "curation"

function SettingsTab() {
  const { settings, isLoading, error, set, remove } = useSettings()
  const [newKey, setNewKey] = useState("")
  const [newValue, setNewValue] = useState("")
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    await set(newKey, { value: newValue })
    setNewKey("")
    setNewValue("")
  }

  const handleUpdate = async (key: string) => {
    await set(key, { value: editValue })
    setEditingKey(null)
  }

  const handleDelete = async (key: string) => {
    if (confirm(`Delete setting "${key}"?`)) {
      await remove(key)
    }
  }

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <form onSubmit={handleCreate} className="flex gap-2">
        <input
          type="text" placeholder="Key" value={newKey} onChange={(e) => setNewKey(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="text" placeholder="Value" value={newValue} onChange={(e) => setNewValue(e.target.value)} required
          className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button type="submit" className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700">
          Add
        </button>
      </form>

      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Key</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Value</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Updated</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && settings.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">Loading...</td></tr>
            ) : settings.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">No settings</td></tr>
            ) : (
              settings.map((s) => (
                <tr key={s.key} className="border-b border-gray-100">
                  <td className="px-4 py-2 text-sm font-mono">{s.key}</td>
                  <td className="px-4 py-2 text-sm">
                    {editingKey === s.key ? (
                      <input
                        value={editValue} onChange={(e) => setEditValue(e.target.value)}
                        className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                      />
                    ) : (
                      <span className="font-mono">{s.value}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-400">
                    {new Date(s.updated_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-sm space-x-1">
                    {editingKey === s.key ? (
                      <>
                        <button onClick={() => handleUpdate(s.key)} className="rounded bg-green-100 px-2 py-1 text-xs text-green-700">Save</button>
                        <button onClick={() => setEditingKey(null)} className="rounded bg-gray-100 px-2 py-1 text-xs">Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => { setEditingKey(s.key); setEditValue(s.value) }} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
                        <button onClick={() => handleDelete(s.key)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CurationTab() {
  const { providers, models, fetchModels, setCuration, removeCuration } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels: ModelMetaDto[] = selectedProvider ? (models.get(selectedProvider) ?? []) : []

  const handleSetRating = async (model: ModelMetaDto, rating: ModelRating) => {
    await setCuration(model.provider_id, model.model_id, {
      overall_rating: rating,
      hidden: model.curation?.hidden ?? false,
      admin_description: model.curation?.admin_description ?? null,
    })
  }

  const handleToggleHidden = async (model: ModelMetaDto) => {
    const hidden = !(model.curation?.hidden ?? false)
    await setCuration(model.provider_id, model.model_id, {
      overall_rating: model.curation?.overall_rating ?? "available",
      hidden,
      admin_description: model.curation?.admin_description ?? null,
    })
  }

  const handleRemoveCuration = async (model: ModelMetaDto) => {
    await removeCuration(model.provider_id, model.model_id)
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {providers.filter((p) => p.is_configured).map((p) => (
          <button
            key={p.provider_id}
            onClick={() => handleSelectProvider(p.provider_id)}
            className={`rounded px-3 py-1.5 text-sm ${selectedProvider === p.provider_id ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"}`}
          >
            {p.display_name}
          </button>
        ))}
      </div>

      {selectedProvider && (
        <div className="space-y-2">
          {providerModels.map((m) => (
            <div key={m.unique_id} className="rounded border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium">{m.display_name}</span>
                  <span className="ml-2 text-xs text-gray-400">{m.model_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  {(["available", "recommended", "not_recommended"] as ModelRating[]).map((rating) => (
                    <button
                      key={rating}
                      onClick={() => handleSetRating(m, rating)}
                      className={`rounded px-2 py-1 text-xs ${
                        m.curation?.overall_rating === rating
                          ? rating === "recommended" ? "bg-green-200 text-green-800"
                            : rating === "not_recommended" ? "bg-red-200 text-red-800"
                            : "bg-blue-200 text-blue-800"
                          : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                      }`}
                    >
                      {rating}
                    </button>
                  ))}
                  <button
                    onClick={() => handleToggleHidden(m)}
                    className={`rounded px-2 py-1 text-xs ${m.curation?.hidden ? "bg-gray-300 text-gray-700" : "bg-gray-100 text-gray-500"}`}
                  >
                    {m.curation?.hidden ? "Hidden" : "Visible"}
                  </button>
                  {m.curation && (
                    <button
                      onClick={() => handleRemoveCuration(m)}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
              {m.curation?.admin_description && (
                <p className="mt-1 text-xs text-gray-400">{m.curation.admin_description}</p>
              )}
            </div>
          ))}
          {providerModels.length === 0 && (
            <p className="text-sm text-gray-400">No models loaded</p>
          )}
        </div>
      )}
    </div>
  )
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("settings")

  const tabClass = (t: Tab) =>
    `rounded-t px-4 py-2 text-sm ${tab === t ? "bg-white border-b-2 border-blue-600 font-medium" : "text-gray-500 hover:text-gray-700"}`

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Admin</h2>
      <div className="flex gap-1 border-b border-gray-200">
        <button onClick={() => setTab("settings")} className={tabClass("settings")}>Settings</button>
        <button onClick={() => setTab("curation")} className={tabClass("curation")}>Model Curation</button>
      </div>
      {tab === "settings" && <SettingsTab />}
      {tab === "curation" && <CurationTab />}
    </div>
  )
}
