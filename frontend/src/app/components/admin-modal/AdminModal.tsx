import { useEffect, useRef } from 'react'
import { UsersTab } from './UsersTab'
import { ModelsTab } from './ModelsTab'
import { SystemTab } from './SystemTab'
import { DebugTab } from './DebugTab'
import { OllamaTab } from './OllamaTab'

export type AdminModalTab = 'users' | 'models' | 'system' | 'debug' | 'ollama'

interface Tab {
  id: AdminModalTab
  label: string
}

const TABS: Tab[] = [
  { id: 'users', label: 'Users' },
  { id: 'models', label: 'Models' },
  { id: 'system', label: 'System' },
  { id: 'debug', label: 'Debug' },
  { id: 'ollama', label: 'Ollama Local' },
]

interface AdminModalProps {
  activeTab: AdminModalTab
  onClose: () => void
  onTabChange: (tab: AdminModalTab) => void
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function AdminModal({ activeTab, onClose, onTabChange }: AdminModalProps) {
  const modalRef = useRef<HTMLDivElement>(null)

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
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden
      />

      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-label="Admin Area"
        tabIndex={-1}
        className="absolute inset-0 lg:inset-4 z-20 flex flex-col bg-surface border-0 lg:border lg:border-white/8 rounded-none lg:rounded-xl shadow-2xl overflow-hidden outline-none"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/6 flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px]">🪄</span>
            <span className="text-[13px] font-semibold text-white/80">Admin</span>
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

        <div role="tablist" aria-label="Admin sections" className="flex flex-wrap border-b border-white/6 px-4 flex-shrink-0">
          {TABS.map((tab) => {
            const selected = activeTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                id={`admin-tab-${tab.id}`}
                aria-selected={selected}
                aria-controls={`admin-tabpanel-${tab.id}`}
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
              </button>
            )
          })}
        </div>

        <div
          role="tabpanel"
          id={`admin-tabpanel-${activeTab}`}
          aria-labelledby={`admin-tab-${activeTab}`}
          className="flex-1 overflow-hidden flex flex-col"
        >
          {activeTab === 'users' && <UsersTab />}
          {activeTab === 'models' && <ModelsTab />}
          {activeTab === 'system' && <SystemTab />}
          {activeTab === 'debug' && <DebugTab />}
          {activeTab === 'ollama' && <OllamaTab />}
        </div>
      </div>
    </>
  )
}
