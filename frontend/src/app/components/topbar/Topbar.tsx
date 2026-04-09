import { useEffect, useState } from "react"
import { useLocation, useMatch, useNavigate } from "react-router-dom"
import { useEventStore } from "../../../core/store/eventStore"
import { CHAKRA_PALETTE } from "../../../core/types/chakra"
import { llmApi } from "../../../core/api/llm"
import type { ProviderCredentialDto } from "../../../core/types/llm"
import { CroppedAvatar } from "../avatar-crop/CroppedAvatar"
import type { PersonaDto } from "../../../core/types/persona"
import { useProviderStatusBootstrap } from "../../../core/hooks/useProviderStatusBootstrap"
import { ProviderPill } from "./ProviderPill"
import { JobsPill } from "./JobsPill"

const SECTION_TITLES: Record<string, string> = {
  "/personas": "Personas",
  "/projects": "Projects",
  "/history": "History",
  "/knowledge": "Knowledge",
}

function LivePill({ isLive, wsStatus }: { isLive: boolean; wsStatus: string }) {
  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px]
        ${isLive ? "border-white/7 bg-white/4 text-white/35" : "border-white/5 bg-white/2 text-white/20"}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-live" : "bg-white/20"}`} />
      {wsStatus}
    </span>
  )
}

interface TopbarProps {
  personas: PersonaDto[]
  onOpenPersonaOverlay?: (personaId: string) => void
}

export function Topbar({ personas, onOpenPersonaOverlay }: TopbarProps) {
  useProviderStatusBootstrap()
  const wsStatus = useEventStore((s) => s.status)
  const navigate = useNavigate()
  const location = useLocation()
  const [showAvatar, setShowAvatar] = useState(false)
  const [providers, setProviders] = useState<ProviderCredentialDto[]>([])

  useEffect(() => {
    llmApi.listProviders().then(setProviders).catch(() => {})
  }, [])

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")

  const isLive = wsStatus === "connected"

  if (chatMatch) {
    const { personaId } = chatMatch.params
    const persona = personas.find((p) => p.id === personaId)
    const chakra = persona ? CHAKRA_PALETTE[persona.colour_scheme] : null
    const hasAvatar = !!persona?.profile_image

    return (
      <header className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/6 bg-surface px-4">
        {persona && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => navigate("/personas")}
              title="All personas"
              className="flex h-7 w-7 items-center justify-center rounded-full text-[13px] text-white/30 transition-colors hover:bg-white/8 hover:text-white/55"
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
                <rect x="1" y="1" width="6" height="6" rx="1.5" />
                <rect x="9" y="1" width="6" height="6" rx="1.5" />
                <rect x="1" y="9" width="6" height="6" rx="1.5" />
                <rect x="9" y="9" width="6" height="6" rx="1.5" />
              </svg>
            </button>
            <div
              className="relative"
              onMouseEnter={() => hasAvatar && setShowAvatar(true)}
              onMouseLeave={() => setShowAvatar(false)}
            >
              <button
                type="button"
                onClick={() => onOpenPersonaOverlay?.(persona.id)}
                className="flex items-center gap-2 rounded-full border border-white/8 bg-white/5 px-3 py-1 text-[13px] font-medium text-white/75 transition-colors hover:bg-white/8"
              >
                <span className="h-2 w-2 rounded-full bg-purple" />
                {persona.name}
              </button>

              {/* Avatar popup on hover */}
              {showAvatar && hasAvatar && chakra && (
                <div
                  className="absolute left-0 top-full mt-2 z-50 rounded-2xl shadow-2xl overflow-hidden pointer-events-none p-1.5"
                  style={{
                    backgroundColor: '#13101e',
                    border: `1px solid ${chakra.hex}33`,
                    boxShadow: `0 0 20px ${chakra.glow}, 0 8px 32px rgba(0,0,0,0.5)`,
                  }}
                >
                  <CroppedAvatar
                    personaId={persona.id}
                    updatedAt={persona.updated_at}
                    crop={persona.profile_crop}
                    size={160}
                    alt={persona.name}
                    className="rounded-xl"
                  />
                </div>
              )}
            </div>
          </div>
        )}
        {persona && (() => {
          const [providerId, ...slugParts] = persona.model_unique_id.split(":")
          const slug = slugParts.join(":") || persona.model_unique_id
          const providerName = providers.find((p) => p.provider_id === providerId)?.display_name
          const pillText = providerName ? `${providerName}: ${slug}` : slug
          return (
            <span className="rounded-full border border-gold/20 bg-gold/5 px-2.5 py-0.5 font-mono text-[11px] text-gold">
              {pillText}
            </span>
          )
        })()}
        <div className="ml-auto flex-shrink-0 flex items-center gap-1.5">
          <JobsPill personas={personas} />
          <LivePill isLive={isLive} wsStatus={wsStatus} />
          <ProviderPill provider="ollama_local" label="Local Ollama" />
        </div>
      </header>
    )
  }

  const path = location.pathname
  const title = SECTION_TITLES[path] ?? ""

  return (
    <header className="flex h-[50px] flex-shrink-0 items-center gap-4 border-b border-white/6 bg-surface px-4">
      <span className="text-[13px] font-semibold text-white/60">{title}</span>
      <div className="ml-auto flex items-center gap-2">
        <JobsPill personas={personas} />
        <LivePill isLive={isLive} wsStatus={wsStatus} />
        <ProviderPill provider="ollama_local" label="Local Ollama" />
      </div>
    </header>
  )
}
