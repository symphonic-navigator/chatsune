import { useMemo, useState } from 'react'
import { useEnrichedModels } from '../../../core/hooks/useEnrichedModels'
import type { EnrichedModelDto } from '../../../core/types/llm'
import { applyModelFilters, sortModels, type ModelFilters } from './modelFilters'
import { ModelConfigModal } from './ModelConfigModal'

export interface LockedFilters {
  capTools?: true
  capVision?: true
  capReason?: true
}

interface ModelBrowserProps {
  /** When set, rows become clickable and invoke onSelect instead of opening the config modal. */
  onSelect?: (model: EnrichedModelDto) => void
  currentModelId?: string | null
  lockedFilters?: LockedFilters
}

/**
 * Grouped model browser — one section per Connection, with filter chips
 * for capabilities and favourites. Admin curation is gone; the only
 * per-model state is the user's own config (favourite / hidden / custom
 * display name / custom context window / notes / system prompt addition).
 */
export function ModelBrowser({ onSelect, currentModelId, lockedFilters }: ModelBrowserProps) {
  const { groups, loading, error, refresh } = useEnrichedModels()
  const [filters, setFilters] = useState<ModelFilters>({})
  const [search, setSearch] = useState('')
  const [configModel, setConfigModel] = useState<EnrichedModelDto | null>(null)

  const effectiveFilters = useMemo<ModelFilters>(() => ({
    ...filters,
    search,
    capTools: filters.capTools || !!lockedFilters?.capTools,
    capVision: filters.capVision || !!lockedFilters?.capVision,
    capReason: filters.capReason || !!lockedFilters?.capReason,
  }), [filters, search, lockedFilters])

  const filteredGroups = useMemo(() => {
    return groups
      .map((g) => ({
        connection: g.connection,
        models: sortModels(applyModelFilters(g.models, effectiveFilters), { field: 'name', direction: 'asc' }),
      }))
      .filter((g) => g.models.length > 0)
  }, [groups, effectiveFilters])

  if (loading) {
    return <div className="p-6 text-sm text-white/60">Loading models…</div>
  }

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm text-red-300">{error}</p>
        <button
          type="button"
          onClick={() => { void refresh() }}
          className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
        >
          Try again
        </button>
      </div>
    )
  }

  if (groups.length === 0) {
    return (
      <div className="p-6 text-sm text-white/60">
        No LLM connection configured. Add one in the "LLM Providers" tab.
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-white/6 px-4 py-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search model name…"
          className="flex-1 min-w-[180px] rounded bg-white/5 border border-white/10 px-3 py-1 text-[12px] text-white/85 placeholder:text-white/30 outline-none focus:border-white/25"
        />
        <Chip
          active={!!filters.favouritesOnly}
          onClick={() => setFilters((f) => ({ ...f, favouritesOnly: !f.favouritesOnly }))}
        >
          ★ Favourites
        </Chip>
        <Chip
          active={!!filters.capReason}
          locked={!!lockedFilters?.capReason}
          onClick={() => setFilters((f) => ({ ...f, capReason: !f.capReason }))}
        >
          Reasoning
        </Chip>
        <Chip
          active={!!filters.capVision}
          locked={!!lockedFilters?.capVision}
          onClick={() => setFilters((f) => ({ ...f, capVision: !f.capVision }))}
        >
          Vision
        </Chip>
        <Chip
          active={!!filters.capTools}
          locked={!!lockedFilters?.capTools}
          onClick={() => setFilters((f) => ({ ...f, capTools: !f.capTools }))}
        >
          Tools
        </Chip>
        <Chip
          active={!!filters.showHidden}
          onClick={() => setFilters((f) => ({ ...f, showHidden: !f.showHidden }))}
        >
          Show hidden
        </Chip>
      </div>

      {/* Grouped list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {filteredGroups.length === 0 && (
          <div className="p-6 text-[13px] text-white/50">No models match the current filters.</div>
        )}
        {filteredGroups.map((group) => (
          <section key={group.connection.id} className="mb-4">
            <header className="flex items-baseline gap-2 border-b border-white/6 px-3 py-2">
              <h4 className="text-[13px] font-semibold text-white/85">
                {group.connection.display_name}
              </h4>
              <span className="text-[11px] font-mono text-white/35">
                {group.connection.slug}
              </span>
            </header>
            <ul className="divide-y divide-white/5">
              {group.models.map((model) => (
                <ModelRow
                  key={model.unique_id}
                  model={model}
                  isCurrent={model.unique_id === currentModelId}
                  onSelect={onSelect}
                  onEdit={() => setConfigModel(model)}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>

      {configModel && (
        <ModelConfigModal
          model={configModel}
          onClose={() => setConfigModel(null)}
          onSaved={() => {
            setConfigModel(null)
            void refresh()
          }}
        />
      )}
    </div>
  )
}

interface ModelRowProps {
  model: EnrichedModelDto
  isCurrent: boolean
  onSelect?: (model: EnrichedModelDto) => void
  onEdit: () => void
}

function ModelRow({ model, isCurrent, onSelect, onEdit }: ModelRowProps) {
  const displayName = model.user_config?.custom_display_name ?? model.display_name
  const contextWindow = model.user_config?.custom_context_window ?? model.context_window
  const isFavourite = !!model.user_config?.is_favourite
  const isHidden = !!model.user_config?.is_hidden

  const handleRowClick = () => {
    if (onSelect) {
      onSelect(model)
    } else {
      onEdit()
    }
  }

  return (
    <li
      className={[
        'flex items-center gap-3 px-3 py-2 hover:bg-white/5 cursor-pointer transition-colors',
        isCurrent ? 'bg-white/5' : '',
        isHidden ? 'opacity-60' : '',
      ].join(' ')}
      onClick={handleRowClick}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {isFavourite && <span className="text-gold text-[12px]">★</span>}
          <span className="text-[13px] text-white/85 truncate">{displayName}</span>
          {isCurrent && (
            <span className="rounded bg-purple/30 px-1.5 py-0.5 text-[10px] text-white/85">
              aktuell
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-0.5 text-[11px] text-white/45 font-mono">
          <span>{model.model_id}</span>
          <span>·</span>
          <span>ctx {Number.isFinite(contextWindow) ? contextWindow.toLocaleString() : '?'}</span>
          {model.parameter_count && (
            <>
              <span>·</span>
              <span>{model.parameter_count}</span>
            </>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {model.supports_reasoning && <CapBadge label="R" title="Reasoning" />}
        {model.supports_vision && <CapBadge label="V" title="Vision" />}
        {model.supports_tool_calls && <CapBadge label="T" title="Tools" />}
      </div>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onEdit() }}
        className="rounded border border-white/10 px-2 py-0.5 text-[11px] text-white/70 hover:bg-white/5"
        aria-label="Configure model"
        title="Configure model"
      >
        Edit
      </button>
    </li>
  )
}

function Chip({
  active,
  locked,
  onClick,
  children,
}: {
  active: boolean
  locked?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={locked}
      className={[
        'rounded-full px-3 py-1 text-[11px] transition-colors',
        active
          ? 'bg-purple/70 text-white'
          : 'bg-white/5 text-white/65 hover:bg-white/10',
        locked ? 'opacity-70 cursor-not-allowed' : '',
      ].join(' ')}
      title={locked ? 'Durch Kontext vorgegeben' : undefined}
    >
      {children}
    </button>
  )
}

function CapBadge({ label, title }: { label: string; title: string }) {
  return (
    <span
      className="inline-flex h-4 w-4 items-center justify-center rounded border border-white/15 text-[9px] text-white/60"
      title={title}
      aria-label={title}
    >
      {label}
    </span>
  )
}
