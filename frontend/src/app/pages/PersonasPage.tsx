import { useRef, useState } from "react"
import { useNavigate, useOutletContext } from "react-router-dom"
import PersonaCard from "../components/persona-card/PersonaCard"
import AddPersonaCard from "../components/persona-card/AddPersonaCard"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { useSanitisedMode } from "../../core/store/sanitisedModeStore"
import { useNotificationStore } from "../../core/store/notificationStore"
import { personasApi } from "../../core/api/personas"
import { ApiError } from "../../core/api/client"
import type { PersonaOverlayTab } from "../components/persona-overlay/PersonaOverlay"

export default function PersonasPage() {
  const { personas, update } = usePersonas()
  const { sessions } = useChatSessions()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const navigate = useNavigate()
  const { openPersonaOverlay } = useOutletContext<{
    openPersonaOverlay: (personaId: string | null, tab?: PersonaOverlayTab) => void
  }>()

  const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas

  const handleContinue = (personaId: string) => {
    const lastSession = sessions.find((s) => s.persona_id === personaId)
    if (lastSession) {
      navigate(`/chat/${personaId}/${lastSession.id}`)
    } else {
      navigate(`/chat/${personaId}?new=1`)
    }
  }

  const handleNewChat = (personaId: string) => {
    navigate(`/chat/${personaId}?new=1`)
  }

  const handleOpenOverlay = (personaId: string, tab: PersonaOverlayTab) => {
    openPersonaOverlay(personaId, tab)
  }

  const handleTogglePin = (personaId: string, pinned: boolean) => {
    update(personaId, { pinned })
  }

  const addNotification = useNotificationStore((s) => s.addNotification)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)

  const handleCreateNew = () => {
    openPersonaOverlay(null, "edit")
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    // Reset the input so picking the same file again will re-trigger onChange.
    event.target.value = ""
    if (!file) return

    setImporting(true)
    try {
      const created = await personasApi.importPersona(file)
      addNotification({
        level: "success",
        title: "Persona imported",
        message: `${created.name} has been imported.`,
      })
      // Navigate to the newly-imported persona's overview so it feels like
      // "just another way to create a persona". The PERSONA_CREATED WS
      // event will repopulate the list via usePersonas.
      openPersonaOverlay(created.id, "overview")
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to import persona."
      addNotification({
        level: "error",
        title: "Import failed",
        message,
      })
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-10">
      <div
        className="flex flex-wrap justify-center gap-4 sm:gap-6"
        style={{ maxWidth: "1200px", margin: "0 auto" }}
      >
        {filtered.map((persona, index) => (
          <PersonaCard
            key={persona.id}
            persona={persona}
            index={index}
            onContinue={handleContinue}
            onNewChat={handleNewChat}
            onOpenOverlay={handleOpenOverlay}
            onTogglePin={handleTogglePin}
          />
        ))}
        <AddPersonaCard
          onCreateNew={handleCreateNew}
          onImport={handleImportClick}
          index={filtered.length}
        />
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".tar.gz,.gz,application/gzip"
        className="hidden"
        onChange={handleFileSelected}
      />

      {importing && (
        <div
          className="fixed inset-0 z-[55] flex items-center justify-center bg-black/60"
          role="status"
          aria-live="polite"
          aria-label="Importing persona"
        >
          <div className="flex items-center gap-3 rounded-lg border border-white/8 bg-elevated px-5 py-4 shadow-2xl">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
            <span className="text-[13px] text-white/80">Importing persona…</span>
          </div>
        </div>
      )}
    </div>
  )
}
