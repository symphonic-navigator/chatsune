import { useCallback, useEffect, useRef, useState } from 'react'
import { AboutMeTab } from './AboutMeTab'
import { SettingsTab } from './SettingsTab'
import { HistoryTab } from './HistoryTab'
// Projects UI hidden — feature not yet ready (see FOR_LATER.md).
import { KnowledgeTab } from './KnowledgeTab'
import { UploadsTab } from './UploadsTab'
import { ArtefactsTab } from './ArtefactsTab'
import { BookmarksTab } from './BookmarksTab'
import { ModelsTab } from './ModelsTab'
import { JobLogTab } from './JobLogTab'
import { ApiKeysTab } from './ApiKeysTab'
import { PersonasTab } from './PersonasTab'
import { McpTab } from './McpTab'
import { IntegrationsTab } from './IntegrationsTab'
import { LlmProvidersTab } from './LlmProvidersTab'
import { llmApi } from '../../../core/api/llm'
import { webSearchApi } from '../../../core/api/websearch'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'
import { TABS_TREE, type TopTabId, type SubTabId } from './userModalTree'
import { useSubtabStore } from './userModalSubtabStore'

// Re-export for backwards compatibility — consumers that imported UserModalTab
// by name from this module will still compile.
export type { TopTabId, SubTabId }

/**
 * @deprecated Use TopTabId / SubTabId. Kept so existing imports do not break
 * during the transition period.
 */
export type UserModalTab = TopTabId | SubTabId

interface UserModalProps {
  activeTop: TopTabId
  activeSub: SubTabId | undefined
  onClose: () => void
  onTabChange: (top: TopTabId, sub?: SubTabId) => void
  displayName: string
  /**
   * Kept on the prop-surface for callers that still pass it. The badge
   * source of truth now lives inside this modal (web-search credentials).
   */
  hasApiKeyProblem?: boolean
  /**
   * Retained as a stub for AppLayout compatibility. Downstream consumers
   * have their own event subscriptions now.
   */
  onProvidersChanged?: () => void
  onOpenPersonaOverlay: (personaId: string) => void
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function UserModal({
  activeTop,
  activeSub,
  onClose,
  onTabChange,
  displayName,
  onProvidersChanged,
  onOpenPersonaOverlay,
}: UserModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)
  const setLastSub = useSubtabStore((s) => s.setLastSub)

  // LLM-connection badge: an exclamation flag appears on the LLM Providers
  // sub-tab (and propagated to the Settings top-pill) when the user has zero
  // connections configured.
  const [hasNoLlmConnection, setHasNoLlmConnection] = useState(false)

  // API-key badge: flips to true when any web-search provider is missing its
  // credential. Propagated to the Settings top-pill.
  const [hasApiKeyProblem, setHasApiKeyProblem] = useState(false)

  // True when either of the above flags is set — shown on the Settings top-pill.
  const settingsHasProblem = hasNoLlmConnection || hasApiKeyProblem

  const refreshConnectionCount = useCallback(async () => {
    try {
      const conns = await llmApi.listConnections()
      setHasNoLlmConnection(conns.length === 0)
    } catch {
      // Best-effort — silently ignore. The badge defaults to "no problem".
    }
  }, [])

  const refreshWebSearchGaps = useCallback(async () => {
    try {
      const providers = await webSearchApi.listWebSearchProviders()
      setHasApiKeyProblem(providers.some((p) => !p.is_configured))
    } catch {
      // Best-effort — silently ignore.
    }
  }, [])

  useEffect(() => {
    void refreshConnectionCount()
    const topics = [
      Topics.LLM_CONNECTION_CREATED,
      Topics.LLM_CONNECTION_REMOVED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refreshConnectionCount() }))
    return () => unsubs.forEach((u) => u())
  }, [refreshConnectionCount])

  useEffect(() => {
    void refreshWebSearchGaps()
    const topics = [
      Topics.WEBSEARCH_CREDENTIAL_SET,
      Topics.WEBSEARCH_CREDENTIAL_REMOVED,
      Topics.WEBSEARCH_CREDENTIAL_TESTED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refreshWebSearchGaps() }))
    return () => unsubs.forEach((u) => u())
  }, [refreshWebSearchGaps])

  // Focus trap + Escape key
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    modalRef.current?.focus()

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab') return

      const focusable = modalRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)
      if (!focusable || focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previousFocus?.focus()
    }
  }, [onClose])

  // The active sub-tab node from the tree (null for leaf-only top tabs)
  const activeTopNode = TABS_TREE.find((t) => t.id === activeTop)
  const subTabs = activeTopNode?.children ?? []

  /** Derive the content key: prefer activeSub if it belongs to the current top,
   *  otherwise fall back to the top id itself (for leaf-only tops). */
  const contentKey: TopTabId | SubTabId = activeSub ?? activeTop

  function handleTopClick(top: TopTabId) {
    onTabChange(top)
  }

  function handleSubClick(sub: SubTabId) {
    setLastSub(activeTop, sub)
    onTabChange(activeTop, sub)
  }

  return (
    <>
      {/* Backdrop — covers entire screen, clicking it closes the modal */}
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden
      />

      {/* Modal box */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label="User Area"
        tabIndex={-1}
        className="absolute inset-0 lg:inset-4 z-20 flex flex-col bg-surface border-0 lg:border lg:border-white/8 rounded-none lg:rounded-xl shadow-2xl overflow-hidden outline-none"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/6 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-white/80">{displayName}</span>
            <span className="text-[11px] text-white/30">· User Area</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close user area"
            title="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Top-level tab bar (row 1) */}
        <div role="tablist" aria-label="User area sections" className="flex flex-wrap border-b border-white/6 px-4 flex-shrink-0">
          {TABS_TREE.map((tab) => {
            const selected = activeTop === tab.id
            const showBadge = tab.id === 'settings' && settingsHasProblem
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`user-tab-${tab.id}`}
                aria-selected={selected}
                aria-controls={`user-tabpanel-${tab.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => handleTopClick(tab.id)}
                className={[
                  'px-3 py-2.5 text-[12px] border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap',
                  selected
                    ? 'border-gold text-gold'
                    : 'border-transparent text-white/60 hover:text-white/80 hover:underline',
                ].join(' ')}
              >
                {tab.label}
                {showBadge && (
                  <span className="ml-1.5 text-[10px] text-red-400" title="Attention required" aria-label="Attention required">!</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Sub-tab bar (row 2) — only rendered when the active top has children */}
        {subTabs.length > 0 && (
          <div role="tablist" aria-label={`${activeTopNode?.label ?? ''} sub-sections`} className="flex flex-wrap gap-1 px-4 py-2 border-b border-white/6 bg-white/2 flex-shrink-0">
            {subTabs.map((sub) => {
              const selected = activeSub === sub.id
              const showSubBadge =
                (sub.id === 'api-keys' && hasApiKeyProblem) ||
                (sub.id === 'llm-providers' && hasNoLlmConnection)
              return (
                <button
                  key={sub.id}
                  type="button"
                  role="tab"
                  id={`user-subtab-${sub.id}`}
                  aria-selected={selected}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => handleSubClick(sub.id)}
                  className={[
                    'px-2.5 py-1 text-[11px] rounded-full cursor-pointer transition-colors whitespace-nowrap',
                    selected
                      ? 'bg-gold/15 text-gold'
                      : 'text-white/50 hover:text-white/80 hover:bg-white/6',
                  ].join(' ')}
                >
                  {sub.label}
                  {showSubBadge && (
                    <span className="ml-1 text-[10px] text-red-400" title="Attention required" aria-label="Attention required">!</span>
                  )}
                </button>
              )
            })}
          </div>
        )}

        {/* Tab content */}
        <div
          role="tabpanel"
          id={`user-tabpanel-${contentKey}`}
          aria-labelledby={`user-tab-${contentKey}`}
          className="flex-1 overflow-hidden flex flex-col"
        >
          {contentKey === 'about-me' && <AboutMeTab />}
          {contentKey === 'personas' && <PersonasTab onOpenPersonaOverlay={onOpenPersonaOverlay} />}
          {/* Projects tab hidden — feature not yet ready (see FOR_LATER.md). */}
          {contentKey === 'history' && <HistoryTab onClose={onClose} />}
          {contentKey === 'knowledge' && <KnowledgeTab />}
          {contentKey === 'bookmarks' && <BookmarksTab onClose={onClose} />}
          {contentKey === 'llm-providers' && <LlmProvidersTab />}
          {contentKey === 'uploads' && <UploadsTab />}
          {contentKey === 'artefacts' && <ArtefactsTab onClose={onClose} />}
          {contentKey === 'models' && <ModelsTab />}
          {contentKey === 'job-log' && <JobLogTab />}
          {contentKey === 'display' && <SettingsTab />}
          {contentKey === 'api-keys' && <ApiKeysTab onProvidersLoaded={onProvidersChanged} />}
          {contentKey === 'mcp' && <McpTab />}
          {contentKey === 'integrations' && <IntegrationsTab />}
        </div>
      </div>
    </>
  )
}
