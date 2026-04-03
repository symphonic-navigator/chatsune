import { useState } from "react"
import { useLlm } from "../../core/hooks/useLlm"
import type { ModelMetaDto } from "../../core/types/llm"

type Tab = "credentials" | "models" | "config"

function CredentialsTab() {
  const { providers, setKey, removeKey, testKey, isLoading } = useLlm()
  const [editingProvider, setEditingProvider] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState("")
  const [testResult, setTestResult] = useState<{ provider: string; valid: boolean } | null>(null)

  const handleSetKey = async (providerId: string) => {
    await setKey(providerId, { api_key: apiKey })
    setEditingProvider(null)
    setApiKey("")
  }

  const handleTest = async (providerId: string) => {
    if (!apiKey) return
    const res = await testKey(providerId, { api_key: apiKey })
    setTestResult({ provider: providerId, valid: res.valid })
  }

  return (
    <div className="space-y-3">
      {providers.map((p) => (
        <div key={p.provider_id} className="rounded border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-medium text-sm">{p.display_name}</span>
              <span className="ml-2 text-xs text-gray-400">{p.provider_id}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded px-2 py-0.5 text-xs ${p.is_configured ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                {p.is_configured ? "Configured" : "Not configured"}
              </span>
              {p.is_configured && (
                <button onClick={() => removeKey(p.provider_id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">
                  Remove
                </button>
              )}
              <button onClick={() => { setEditingProvider(p.provider_id); setApiKey(""); setTestResult(null) }} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">
                {p.is_configured ? "Change Key" : "Set Key"}
              </button>
            </div>
          </div>
          {editingProvider === p.provider_id && (
            <div className="mt-3 flex items-center gap-2">
              <input
                type="password" placeholder="API Key" value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              />
              <button onClick={() => handleTest(p.provider_id)} className="rounded bg-amber-100 px-3 py-1.5 text-xs text-amber-700 hover:bg-amber-200">
                Test
              </button>
              <button onClick={() => handleSetKey(p.provider_id)} className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700">
                Save
              </button>
              <button onClick={() => setEditingProvider(null)} className="rounded bg-gray-100 px-3 py-1.5 text-xs hover:bg-gray-200">
                Cancel
              </button>
              {testResult?.provider === p.provider_id && (
                <span className={`text-xs ${testResult.valid ? "text-green-600" : "text-red-600"}`}>
                  {testResult.valid ? "Valid" : "Invalid"}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
      {providers.length === 0 && !isLoading && (
        <p className="text-sm text-gray-400">No providers available</p>
      )}
    </div>
  )
}

function ModelsTab() {
  const { providers, models, fetchModels } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels: ModelMetaDto[] = selectedProvider ? (models.get(selectedProvider) ?? []) : []

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
        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Model</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Context</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Capabilities</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Rating</th>
              </tr>
            </thead>
            <tbody>
              {providerModels.map((m) => (
                <tr key={m.unique_id} className="border-b border-gray-100">
                  <td className="px-4 py-2">
                    <div className="text-sm font-medium">{m.display_name}</div>
                    <div className="text-xs text-gray-400">{m.model_id}</div>
                  </td>
                  <td className="px-4 py-2 text-sm">{(m.context_window / 1024).toFixed(0)}k</td>
                  <td className="px-4 py-2 text-sm space-x-1">
                    {m.supports_reasoning && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">reasoning</span>}
                    {m.supports_vision && <span className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-600">vision</span>}
                    {m.supports_tool_calls && <span className="rounded bg-purple-50 px-1.5 py-0.5 text-xs text-purple-600">tools</span>}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    {m.curation ? (
                      <span className={`rounded px-2 py-0.5 text-xs ${
                        m.curation.overall_rating === "recommended" ? "bg-green-100 text-green-700" :
                        m.curation.overall_rating === "not_recommended" ? "bg-red-100 text-red-700" :
                        "bg-gray-100 text-gray-600"
                      }`}>
                        {m.curation.overall_rating}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">uncurated</span>
                    )}
                  </td>
                </tr>
              ))}
              {providerModels.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">No models loaded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function UserConfigTab() {
  const { userConfigs, providers, models, fetchModels, setUserConfig } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels = selectedProvider ? (models.get(selectedProvider) ?? []) : []
  const configMap = new Map(userConfigs.map((c) => [c.model_unique_id, c]))

  const toggleFavourite = async (model: ModelMetaDto) => {
    const current = configMap.get(model.unique_id)
    const [providerId, ...slugParts] = model.unique_id.split(":")
    const modelSlug = slugParts.join(":")
    await setUserConfig(providerId, modelSlug, { is_favourite: !(current?.is_favourite ?? false) })
  }

  const toggleHidden = async (model: ModelMetaDto) => {
    const current = configMap.get(model.unique_id)
    const [providerId, ...slugParts] = model.unique_id.split(":")
    const modelSlug = slugParts.join(":")
    await setUserConfig(providerId, modelSlug, { is_hidden: !(current?.is_hidden ?? false) })
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
          {providerModels.map((m) => {
            const config = configMap.get(m.unique_id)
            return (
              <div key={m.unique_id} className="flex items-center justify-between rounded border border-gray-200 bg-white px-4 py-3">
                <div>
                  <span className="text-sm font-medium">{m.display_name}</span>
                  <span className="ml-2 text-xs text-gray-400">{m.model_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggleFavourite(m)}
                    className={`rounded px-2 py-1 text-xs ${config?.is_favourite ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-500"}`}
                  >
                    {config?.is_favourite ? "Favourited" : "Favourite"}
                  </button>
                  <button
                    onClick={() => toggleHidden(m)}
                    className={`rounded px-2 py-1 text-xs ${config?.is_hidden ? "bg-gray-300 text-gray-700" : "bg-gray-100 text-gray-500"}`}
                  >
                    {config?.is_hidden ? "Hidden" : "Hide"}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function LlmPage() {
  const [tab, setTab] = useState<Tab>("credentials")

  const tabClass = (t: Tab) =>
    `rounded-t px-4 py-2 text-sm ${tab === t ? "bg-white border-b-2 border-blue-600 font-medium" : "text-gray-500 hover:text-gray-700"}`

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">LLM</h2>
      <div className="flex gap-1 border-b border-gray-200">
        <button onClick={() => setTab("credentials")} className={tabClass("credentials")}>Credentials</button>
        <button onClick={() => setTab("models")} className={tabClass("models")}>Models</button>
        <button onClick={() => setTab("config")} className={tabClass("config")}>My Config</button>
      </div>
      {tab === "credentials" && <CredentialsTab />}
      {tab === "models" && <ModelsTab />}
      {tab === "config" && <UserConfigTab />}
    </div>
  )
}
