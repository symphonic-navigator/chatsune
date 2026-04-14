import { useEffect, useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'
import { llmApi } from '../../../core/api/llm'
import type { Adapter, AdapterTemplate, Connection } from '../../../core/types/llm'
import { ConnectionConfigModal, type NewConnectionPreset } from './ConnectionConfigModal'

interface AddConnectionWizardProps {
  onClose: () => void
  onCreated: () => void | Promise<void>
}

/**
 * Suggests a free slug given a template's `slug_prefix` and the existing
 * slugs already used by the user. If the prefix itself is free we use
 * it; otherwise we append `-2`, `-3`, … until we find a gap.
 */
function suggestSlug(prefix: string, existing: ReadonlySet<string>): string {
  if (!existing.has(prefix)) return prefix
  for (let i = 2; i < 1000; i++) {
    const candidate = `${prefix}-${i}`
    if (!existing.has(candidate)) return candidate
  }
  return `${prefix}-${Date.now()}`
}

export function AddConnectionWizard({ onClose, onCreated }: AddConnectionWizardProps) {
  const [adapters, setAdapters] = useState<Adapter[]>([])
  const [existingSlugs, setExistingSlugs] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [chosenAdapter, setChosenAdapter] = useState<Adapter | null>(null)
  const [preset, setPreset] = useState<NewConnectionPreset | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [adapterList, connections] = await Promise.all([
          llmApi.listAdapters(),
          llmApi.listConnections(),
        ])
        if (cancelled) return
        setAdapters(adapterList)
        setExistingSlugs(new Set(connections.map((c: Connection) => c.slug)))
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load adapters.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  function handleAdapterPick(adapter: Adapter) {
    setChosenAdapter(adapter)
    // Auto-skip the template step if there's exactly one template.
    if (adapter.templates.length === 1) {
      handleTemplatePick(adapter, adapter.templates[0])
    }
  }

  function handleTemplatePick(adapter: Adapter, template: AdapterTemplate) {
    const slug = suggestSlug(template.slug_prefix, existingSlugs)
    setPreset({
      adapter_type: adapter.adapter_type,
      display_name: template.display_name,
      slug,
      config: { ...template.config_defaults },
      required_config_fields: [...template.required_config_fields],
    })
  }

  // Once we have a preset we hand off to ConnectionConfigModal.
  if (preset && chosenAdapter) {
    return (
      <ConnectionConfigModal
        newConnectionPreset={preset}
        onClose={onClose}
        onSaved={onCreated}
      />
    )
  }

  return (
    <Sheet
      isOpen={true}
      onClose={onClose}
      size="lg"
      ariaLabel="Add connection"
      className="border border-white/8 bg-elevated"
    >
      <div className="flex max-h-full flex-col">
        <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            {chosenAdapter ? `Choose template — ${chosenAdapter.display_name}` : 'Choose adapter'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading && <p className="text-sm text-white/60">Loading…</p>}
          {error && (
            <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-300">
              {error}
            </p>
          )}

          {!loading && !error && !chosenAdapter && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {adapters.map((adapter) => (
                <button
                  key={adapter.adapter_type}
                  type="button"
                  onClick={() => handleAdapterPick(adapter)}
                  className="flex flex-col gap-1 rounded border border-white/8 bg-black/20 px-4 py-3 text-left hover:border-purple/40 hover:bg-purple/5 cursor-pointer"
                >
                  <span className="text-sm font-medium text-white/90">
                    {adapter.display_name}
                  </span>
                  <span className="font-mono text-[11px] text-white/40">
                    {adapter.adapter_type}
                  </span>
                </button>
              ))}
              {adapters.length === 0 && (
                <p className="col-span-full text-sm text-white/50">
                  No adapters available.
                </p>
              )}
            </div>
          )}

          {!loading && !error && chosenAdapter && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {chosenAdapter.templates.map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    onClick={() => handleTemplatePick(chosenAdapter, template)}
                    className="flex flex-col gap-1 rounded border border-white/8 bg-black/20 px-4 py-3 text-left hover:border-purple/40 hover:bg-purple/5 cursor-pointer"
                  >
                    <span className="text-sm font-medium text-white/90">
                      {template.display_name}
                    </span>
                    <span className="font-mono text-[11px] text-white/40">
                      slug: {template.slug_prefix}
                    </span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setChosenAdapter(null)}
                className="text-[11px] text-white/50 hover:text-white/80 underline"
              >
                ← back
              </button>
            </div>
          )}
        </div>
      </div>
    </Sheet>
  )
}
