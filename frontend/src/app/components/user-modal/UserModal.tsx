import { useEffect, useRef } from 'react'
import { setLastMyDataSubpage, type MyDataSubpage } from './myDataMemory'
import { GalleryGrid } from '../../../features/images/gallery/GalleryGrid'
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
import { PersonasTab } from './PersonasTab'
import { McpTab } from './McpTab'
import { IntegrationsTab } from './IntegrationsTab'
import { LlmProvidersTab } from './LlmProvidersTab'
import { VoiceTab } from './VoiceTab'
import { CommunityProvisioningPage } from '../../../features/community-provisioning/CommunityProvisioningPage'
import { useEnrichedModels } from '../../../core/hooks/useEnrichedModels'
import { TABS_TREE, resolveLeaf, toMobileNavTree, type TopTabId, type SubTabId } from './userModalTree'
import { useSubtabStore } from './userModalSubtabStore'
import { OverlayMobileNav } from '../overlay-mobile-nav/OverlayMobileNav'

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
   * Retained on the prop-surface for backwards compatibility with callers
   * that still pass it. No longer used — web-search credentials are sourced
   * from the Providers tab now.
   */
  hasApiKeyProblem?: boolean
  /**
   * Retained as a stub for AppLayout compatibility. Downstream consumers
   * have their own event subscriptions now.
   */
  onProvidersChanged?: () => void
  onOpenPersonaOverlay: (personaId: string) => void
  onCreatePersona: () => void
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function UserModal({
  activeTop,
  activeSub,
  onClose,
  onTabChange,
  displayName,
  onOpenPersonaOverlay,
  onCreatePersona,
}: UserModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)
  const setLastSub = useSubtabStore((s) => s.setLastSub)

  // LLM-providers badge: an exclamation flag appears on the LLM Providers
  // sub-tab (and propagated to the Settings top-pill) when the user has no
  // usable model — either no custom Connection and no Premium provider
  // account, or every configured source failed its probe and exposes zero
  // models. The enriched-models hub already aggregates both sources and
  // keeps itself live via the relevant topics, so we just derive the flag
  // from its output. While the hub is still loading we suppress the badge
  // to avoid a brief flash on modal open.
  const { groups: modelGroups, loading: modelsLoading } = useEnrichedModels()
  const hasNoLlmConnection =
    !modelsLoading && !modelGroups.some((g) => g.models.length > 0)

  // Only flag currently feeding the Settings top-pill badge.
  const settingsHasProblem = hasNoLlmConnection

  const mobileTree = toMobileNavTree({ 'llm-providers': hasNoLlmConnection })
  const mobileActiveId: string = activeSub ?? activeTop

  function handleMobileSelect(id: string) {
    const resolved = resolveLeaf(id)
    if (resolved.sub) {
      setLastSub(resolved.top, resolved.sub)
      onTabChange(resolved.top, resolved.sub)
    } else {
      onTabChange(resolved.top)
    }
  }

  // Persist the last-visited My data sub-page so re-opening the modal
  // restores the previous position within the My data section.
  useEffect(() => {
    const sub = activeSub ?? activeTop
    if (sub === 'uploads' || sub === 'artefacts' || sub === 'images') {
      setLastMyDataSubpage(sub as MyDataSubpage)
    }
  }, [activeTop, activeSub])

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
        <div role="tablist" aria-label="User area sections" className="hidden lg:flex flex-wrap border-b border-white/6 px-4 flex-shrink-0">
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
          <div role="tablist" aria-label={`${activeTopNode?.label ?? ''} sub-sections`} className="hidden lg:flex flex-wrap gap-1 px-4 py-2 border-b border-white/6 bg-white/2 flex-shrink-0">
            {subTabs.map((sub) => {
              const selected = activeSub === sub.id
              const showSubBadge = sub.id === 'llm-providers' && hasNoLlmConnection
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

        {/* Mobile nav row — replaces the desktop tab rows below lg */}
        <div className="lg:hidden border-b border-white/6 px-4 py-2 bg-white/2 flex-shrink-0">
          <OverlayMobileNav
            tree={mobileTree}
            activeId={mobileActiveId}
            onSelect={handleMobileSelect}
            ariaLabel="Open user area navigation"
          />
        </div>

        {/* Tab content */}
        <div
          role="tabpanel"
          id={`user-tabpanel-${contentKey}`}
          aria-labelledby={`user-tab-${contentKey}`}
          className="flex-1 overflow-hidden flex flex-col"
        >
          {contentKey === 'about-me' && <AboutMeTab />}
          {contentKey === 'personas' && <PersonasTab onOpenPersonaOverlay={onOpenPersonaOverlay} onCreatePersona={onCreatePersona} />}
          {/* Projects tab hidden — feature not yet ready (see FOR_LATER.md). */}
          {contentKey === 'history' && <HistoryTab onClose={onClose} />}
          {contentKey === 'knowledge' && <KnowledgeTab />}
          {contentKey === 'bookmarks' && <BookmarksTab onClose={onClose} />}
          {contentKey === 'llm-providers' && <LlmProvidersTab />}
          {contentKey === 'community-provisioning' && <CommunityProvisioningPage />}
          {contentKey === 'uploads' && <UploadsTab />}
          {contentKey === 'artefacts' && <ArtefactsTab onClose={onClose} />}
          {contentKey === 'images' && (
            <div className="flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
              <GalleryGrid />
            </div>
          )}
          {contentKey === 'models' && <ModelsTab />}
          {contentKey === 'job-log' && <JobLogTab />}
          {contentKey === 'display' && <SettingsTab />}
          {contentKey === 'voice' && <VoiceTab />}
          {contentKey === 'mcp' && <McpTab />}
          {contentKey === 'integrations' && (
            <IntegrationsTab
              onNavigateToSub={(sub) => {
                setLastSub('settings', sub)
                onTabChange('settings', sub)
              }}
            />
          )}
        </div>
      </div>
    </>
  )
}
