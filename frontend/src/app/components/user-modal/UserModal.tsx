import { useEffect, useRef } from 'react'
import { AboutMeTab } from './AboutMeTab'
import { SettingsTab } from './SettingsTab'
import { HistoryTab } from './HistoryTab'
import { ProjectsTab } from './ProjectsTab'
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
import type { ProviderCredentialDto } from '../../../core/types/llm'

export type UserModalTab =
  | 'about-me'
  | 'personas'
  | 'projects'
  | 'history'
  | 'knowledge'
  | 'bookmarks'
  | 'uploads'
  | 'artefacts'
  | 'models'
  | 'job-log'
  | 'settings'
  | 'api-keys'
  | 'mcp'
  | 'integrations'

interface Tab {
  id: UserModalTab
  label: string
}

const TABS: Tab[] = [
  { id: 'about-me', label: 'About me' },
  { id: 'personas', label: 'Personas' },
  { id: 'projects', label: 'Projects' },
  { id: 'history', label: 'History' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'bookmarks', label: 'Bookmarks' },
  { id: 'uploads', label: 'Uploads' },
  { id: 'artefacts', label: 'Artefacts' },
  { id: 'models', label: 'Models' },
  { id: 'job-log', label: 'Job-Log' },
  { id: 'settings', label: 'Settings' },
  { id: 'api-keys', label: 'API-Keys' },
  { id: 'mcp', label: 'MCP' },
  { id: 'integrations', label: 'Integrations' },
]

interface UserModalProps {
  activeTab: UserModalTab
  onClose: () => void
  onTabChange: (tab: UserModalTab) => void
  displayName: string
  hasApiKeyProblem: boolean
  onProvidersChanged: (providers: ProviderCredentialDto[]) => void
  onOpenPersonaOverlay: (personaId: string) => void
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function UserModal({ activeTab, onClose, onTabChange, displayName, hasApiKeyProblem, onProvidersChanged, onOpenPersonaOverlay }: UserModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)

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

        {/* Tab bar */}
        <div role="tablist" aria-label="User area sections" className="flex flex-wrap border-b border-white/6 px-4 flex-shrink-0">
          {TABS.map((tab) => {
            const selected = activeTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`user-tab-${tab.id}`}
                aria-selected={selected}
                aria-controls={`user-tabpanel-${tab.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => onTabChange(tab.id)}
                className={[
                  'px-3 py-2.5 text-[12px] border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap',
                  selected
                    ? 'border-gold text-gold'
                    : 'border-transparent text-white/60 hover:text-white/80 hover:underline',
                ].join(' ')}
              >
                {tab.label}
                {tab.id === 'api-keys' && hasApiKeyProblem && (
                  <span className="ml-1.5 text-[10px] text-red-400" title="API key issue detected" aria-label="API key issue detected">!</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Tab content */}
        <div
          role="tabpanel"
          id={`user-tabpanel-${activeTab}`}
          aria-labelledby={`user-tab-${activeTab}`}
          className="flex-1 overflow-hidden flex flex-col">
          {activeTab === 'about-me' && <AboutMeTab />}
          {activeTab === 'personas' && <PersonasTab onOpenPersonaOverlay={onOpenPersonaOverlay} />}
          {activeTab === 'projects' && <ProjectsTab />}
          {activeTab === 'history' && <HistoryTab onClose={onClose} />}
          {activeTab === 'knowledge' && <KnowledgeTab />}
          {activeTab === 'bookmarks' && <BookmarksTab onClose={onClose} />}
          {activeTab === 'uploads' && <UploadsTab />}
          {activeTab === 'artefacts' && <ArtefactsTab onClose={onClose} />}
          {activeTab === 'models' && <ModelsTab />}
          {activeTab === 'job-log' && <JobLogTab />}
          {activeTab === 'settings' && <SettingsTab />}
          {activeTab === 'api-keys' && <ApiKeysTab onProvidersLoaded={onProvidersChanged} />}
          {activeTab === 'mcp' && <McpTab />}
          {activeTab === 'integrations' && <IntegrationsTab />}
        </div>
      </div>
    </>
  )
}
