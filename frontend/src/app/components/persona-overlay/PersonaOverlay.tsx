import { useEffect, useRef, useState } from 'react'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import type { DeletionReportDto } from '../../../core/types/deletion'
import { DeletionReportSheet } from '../../../core/components/DeletionReportSheet'
import { suggestColour } from '../../../core/utils/suggestColour'
import { personasApi } from '../../../core/api/personas'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { OverviewTab } from './OverviewTab'
import { EditTab } from './EditTab'
import { KnowledgeTab } from './KnowledgeTab'
import { MemoriesTab } from './MemoriesTab'
import { HistoryTab } from './HistoryTab'
import { McpTab } from './McpTab'
import { IntegrationsTab as PersonaIntegrationsTab } from './IntegrationsTab'
import { sttRegistry, ttsRegistry } from '../../../features/voice/engines/registry'
import { PersonaVoiceConfig } from '../../../features/voice/components/PersonaVoiceConfig'
import { useSecretsStore } from '../../../features/integrations/secretsStore'

export type PersonaOverlayTab = 'overview' | 'edit' | 'knowledge' | 'memories' | 'history' | 'mcp' | 'integrations' | 'voice'

interface PersonaOverlayProps {
  persona: PersonaDto | null
  allPersonas: PersonaDto[]
  isCreating?: boolean
  activeTab: PersonaOverlayTab
  onClose: () => void
  onTabChange: (tab: PersonaOverlayTab) => void
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
  onNavigate?: (path: string) => void
  sessions?: Array<{ id: string; persona_id: string; updated_at: string }>
}

const TABS: { id: PersonaOverlayTab; label: string; subtitle?: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'edit', label: 'Edit' },
  { id: 'knowledge', label: 'Knowledge', subtitle: 'muladhara' },
  { id: 'memories', label: 'Memories', subtitle: 'anahata' },
  { id: 'history', label: 'History', subtitle: 'vishuddha' },
  { id: 'mcp', label: 'MCP', subtitle: 'ajna' },
  { id: 'voice', label: 'Voice', subtitle: 'sahasrara' },
  { id: 'integrations', label: 'Integrations' },
]

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

const DEFAULT_PERSONA: PersonaDto = {
  id: '',
  user_id: '',
  name: '',
  tagline: '',
  model_unique_id: '',
  system_prompt: '',
  temperature: 0.8,
  reasoning_enabled: false,
  soft_cot_enabled: false,
  vision_fallback_model: null,
  nsfw: false,
  colour_scheme: 'heart',
  display_order: 0,
  monogram: '?',
  pinned: false,
  profile_image: null,
  profile_crop: null,
  mcp_config: null,
  integrations_config: null,
  voice_config: null,
  created_at: '',
  updated_at: '',
}

export function PersonaOverlay({ persona, allPersonas, isCreating, activeTab, onClose, onTabChange, onSave, onNavigate, sessions }: PersonaOverlayProps) {
  const modalRef = useRef<HTMLDivElement>(null)
  const resolved = persona ?? (isCreating
    ? {
        ...DEFAULT_PERSONA,
        colour_scheme: suggestColour(allPersonas.map((p) => p.colour_scheme)),
      }
    : null)

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

  const addNotification = useNotificationStore((s) => s.addNotification)
  // Subscribe so we re-render on any secrets-store change, ensuring
  // sttRegistry.active()?.isReady() is re-evaluated after secrets hydrate.
  useSecretsStore((s) => s.secrets)
  const voiceEnabled = !!(sttRegistry.active()?.isReady() || ttsRegistry.active()?.isReady())

  // While a deletion report is showing, the modal stays mounted so the
  // user can read the report; navigation away happens only after they
  // dismiss it. See ``handleDismissDeletionReport`` below.
  const [deletionReport, setDeletionReport] = useState<DeletionReportDto | null>(null)

  const handleDeletePersona = async () => {
    if (!resolved?.id) return
    const report = await personasApi.remove(resolved.id)
    setDeletionReport(report)
    addNotification({
      level: report.success ? 'success' : 'warning',
      title: report.success ? 'Persona deleted' : 'Persona deletion partially failed',
      message: report.success
        ? `${resolved.name} has been permanently deleted.`
        : `${resolved.name} could not be fully removed — see the report for details.`,
    })
  }

  const handleDismissDeletionReport = () => {
    setDeletionReport(null)
    onClose()
    onNavigate?.('/personas')
  }

  // When the persona has been deleted out from under us, the main modal must
  // disappear, but the deletion report — which lives in this component's
  // local state — still needs to render so the user actually sees it. If we
  // returned ``null`` here the report would be swallowed along with the
  // overlay; see the PERSONA_DELETED event in ``usePersonas``.
  if (!resolved) {
    return (
      <DeletionReportSheet
        report={deletionReport}
        onClose={handleDismissDeletionReport}
      />
    )
  }

  const chakra = CHAKRA_PALETTE[resolved.colour_scheme]
  const borderColour = `${chakra.hex}26`

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden
      />

      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label={isCreating ? 'New Persona' : `Persona: ${resolved.name}`}
        tabIndex={-1}
        className="absolute inset-0 lg:inset-4 z-20 flex flex-col rounded-none lg:rounded-xl shadow-2xl overflow-hidden outline-none"
        style={{
          background: 'linear-gradient(160deg, #13101e 0%, #0f0d16 100%)',
          border: `1px solid ${borderColour}`,
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-3 flex-shrink-0"
          style={{ borderBottom: `1px solid ${borderColour}` }}
        >
          <div className="flex items-center gap-3">
            {/* Monogram badge */}
            <div
              className="flex items-center justify-center w-7 h-7 rounded-full text-[11px] font-bold text-white/90 flex-shrink-0"
              style={{
                background: `${chakra.hex}33`,
                border: `1px solid ${chakra.hex}55`,
                color: chakra.hex,
              }}
            >
              {resolved.monogram}
            </div>
            <span className="text-[13px] font-semibold text-white/80">
              {isCreating ? 'New Persona' : resolved.name}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Tab bar */}
        <div
          className="flex flex-wrap px-4 flex-shrink-0"
          role="tablist"
          aria-label="Persona sections"
          style={{ borderBottom: `1px solid ${borderColour}` }}
        >
          {TABS
            .filter((tab) => {
              if (isCreating && tab.id !== 'edit') return false
              if (tab.id === 'voice' && !voiceEnabled && activeTab !== 'voice') return false
              return true
            })
            .map((tab) => {
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  id={`persona-tab-${tab.id}`}
                  aria-selected={isActive}
                  aria-controls={`persona-tabpanel-${tab.id}`}
                  tabIndex={isActive ? 0 : -1}
                  onClick={() => onTabChange(tab.id)}
                  className={[
                    'px-3 py-2.5 border-b-2 -mb-px cursor-pointer transition-colors whitespace-nowrap flex flex-col items-start',
                    isActive
                      ? 'text-white/90'
                      : 'border-transparent text-white/45 hover:text-white/70',
                  ].join(' ')}
                  style={isActive ? { borderBottomColor: chakra.hex } : undefined}
                >
                  <span className="text-[12px] leading-none">{tab.label}</span>
                  {tab.subtitle && (
                    <span
                      className="text-[9px] leading-none mt-0.5 font-mono"
                      style={{ color: isActive ? `${chakra.hex}99` : 'rgba(255,255,255,0.6)' }}
                    >
                      {tab.subtitle}
                    </span>
                  )}
                </button>
              )
            })}
        </div>

        {/* Tab content — `relative` anchors the in-parent ModelSelectionModal */}
        <div
          className="relative flex-1 overflow-y-auto"
          role="tabpanel"
          id={`persona-tabpanel-${activeTab}`}
          aria-labelledby={`persona-tab-${activeTab}`}
        >
          {activeTab === 'overview' && !isCreating && (
            <OverviewTab
              persona={resolved}
              chakra={chakra}
              hasLastChat={!!(sessions ?? []).find((s) => s.persona_id === resolved.id)}
              onContinue={() => {
                const last = (sessions ?? [])
                  .filter((s) => s.persona_id === resolved.id)
                  .sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
                if (last) {
                  onNavigate?.(`/chat/${resolved.id}/${last.id}`)
                  onClose()
                }
              }}
              onNewChat={() => {
                onNavigate?.(`/chat/${resolved.id}?new=1`)
                onClose()
              }}
              onNewIncognitoChat={() => {
                onNavigate?.(`/chat/${resolved.id}?incognito=1`)
                onClose()
              }}
              chatCount={(sessions ?? []).filter((s) => s.persona_id === resolved.id).length}
              onGoToHistory={() => onTabChange('history')}
              onDelete={handleDeletePersona}
            />
          )}
          {activeTab === 'edit' && <EditTab persona={resolved} chakra={chakra} onSave={onSave} isCreating={isCreating} />}
          {activeTab === 'knowledge' && !isCreating && <KnowledgeTab persona={resolved} chakra={chakra} />}
          {activeTab === 'memories' && !isCreating && <MemoriesTab persona={resolved} chakra={chakra} />}
          {activeTab === 'history' && !isCreating && <HistoryTab persona={resolved} chakra={chakra} onClose={onClose} />}
          {activeTab === 'mcp' && !isCreating && <McpTab persona={resolved} chakra={chakra} />}
          {activeTab === 'integrations' && !isCreating && <PersonaIntegrationsTab persona={resolved} onSave={onSave} />}
          {activeTab === 'voice' && !isCreating && (
            <PersonaVoiceConfig key={resolved.id} persona={resolved} chakra={chakra} onSave={onSave} />
          )}
        </div>
      </div>
      <DeletionReportSheet
        report={deletionReport}
        onClose={handleDismissDeletionReport}
      />
    </>
  )
}
