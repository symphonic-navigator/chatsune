/**
 * Pick a Chatsune LLM connection + model for an imported session.
 *
 * Shown by ``ChatView`` when the user tries to send a message in a session
 * whose ``model_unique_id`` starts with ``imported:``. After the user picks,
 * ``ChatView`` PATCHes the session via ``chatApi.updateSessionModel`` and
 * then dispatches the original send.
 */
import { useEffect, useMemo, useState } from 'react'

import { Sheet } from '../../core/components/Sheet'
import { llmApi } from '../../core/api/llm'
import type { Connection, ModelMetaDto } from '../../core/types/llm'

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

interface Props {
  isOpen: boolean
  importedModelSlug?: string | null
  onCancel: () => void
  onConfirm: (modelUniqueId: string) => void
}

export function ConnectionPickerDialog({
  isOpen,
  importedModelSlug,
  onCancel,
  onConfirm,
}: Props) {
  const [connections, setConnections] = useState<Connection[]>([])
  const [models, setModels] = useState<ModelMetaDto[]>([])
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null)
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setError(null)
    llmApi
      .listConnections()
      .then((conns) => {
        // Hide system-managed connections — the user can't usefully pick
        // those for arbitrary chat-send (e.g. the embedding-only homelab).
        setConnections(conns.filter((c) => !c.is_system_managed))
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [isOpen])

  useEffect(() => {
    if (!selectedConnectionId) {
      setModels([])
      return
    }
    setLoadingModels(true)
    llmApi
      .listConnectionModels(selectedConnectionId)
      .then((m) => {
        setModels(m)
        // Pre-select a model: try to match the original ChatGPT slug; fall
        // back to the first model.
        const match = importedModelSlug
          ? m.find((mm) => mm.model_id === importedModelSlug)
          : null
        setSelectedModelId(match?.model_id ?? m[0]?.model_id ?? null)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoadingModels(false))
  }, [selectedConnectionId, importedModelSlug])

  const onPick = () => {
    if (selectedConnectionId && selectedModelId) {
      onConfirm(`${selectedConnectionId}:${selectedModelId}`)
    }
  }

  const sortedConnections = useMemo(
    () => [...connections].sort((a, b) => a.display_name.localeCompare(b.display_name)),
    [connections],
  )

  return (
    <Sheet
      isOpen={isOpen}
      onClose={onCancel}
      size="md"
      ariaLabel="Choose connection"
      className="bg-[#0f0d16] text-white"
    >
      <div className="p-6">
        <h2 className="text-xl font-semibold text-white mb-3">Pick a connection</h2>
        <p className="text-white/70 mb-4 text-sm">
          This conversation was imported from ChatGPT
          {importedModelSlug ? (
            <>
              {' '}(originally{' '}
              <code className="font-mono text-xs px-1 py-0.5 bg-white/10 rounded">
                {importedModelSlug}
              </code>)
            </>
          ) : null}
          . Choose the Chatsune connection and model you want to continue with.
        </p>
        {error && (
          <p className="mb-3 text-sm text-red-300">{error}</p>
        )}
        {sortedConnections.length === 0 ? (
          <p className="text-white/60 text-sm mb-4">
            You don&apos;t have any LLM connections set up yet. Add one in
            Settings → LLM → Connections, then come back.
          </p>
        ) : (
          <div className="space-y-2 max-h-64 overflow-y-auto mb-4">
            {sortedConnections.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setSelectedConnectionId(c.id)
                  setSelectedModelId(null)
                }}
                className={
                  selectedConnectionId === c.id
                    ? 'block w-full text-left px-3 py-2 rounded bg-indigo-700 text-white'
                    : 'block w-full text-left px-3 py-2 rounded bg-white/5 text-white/80 hover:bg-white/10'
                }
              >
                <div className="font-medium">{c.display_name}</div>
                <div className="text-xs text-white/50 font-mono">{c.slug}</div>
              </button>
            ))}
          </div>
        )}
        {selectedConnectionId && (
          <div className="mb-4">
            {loadingModels ? (
              <p className="text-sm text-white/50">Loading models…</p>
            ) : models.length === 0 ? (
              <p className="text-sm text-amber-300">
                This connection has no models available.
              </p>
            ) : (
              <select
                value={selectedModelId ?? ''}
                onChange={(e) => setSelectedModelId(e.target.value)}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
              >
                {models.map((m) => (
                  <option key={m.model_id} value={m.model_id} style={OPTION_STYLE}>
                    {m.display_name || m.model_id}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onPick}
            disabled={!selectedConnectionId || !selectedModelId}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded font-medium"
          >
            Use this connection
          </button>
        </div>
      </div>
    </Sheet>
  )
}
