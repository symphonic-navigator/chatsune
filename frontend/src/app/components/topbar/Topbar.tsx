import { useState } from "react"
import { useLocation, useMatch, useNavigate } from "react-router-dom"
import { useEventStore } from "../../../core/store/eventStore"
import { CHAKRA_PALETTE } from "../../../core/types/chakra"
import { CroppedAvatar } from "../avatar-crop/CroppedAvatar"
import type { PersonaDto } from "../../../core/types/persona"
import { useEnrichedModels } from "../../../core/hooks/useEnrichedModels"
import { JobsPill } from "./JobsPill"
import { useDrawerStore } from "../../../core/store/drawerStore"

const SECTION_TITLES: Record<string, string> = {
  "/personas": "Personas",
  "/projects": "Projects",
  "/history": "History",
  "/knowledge": "Knowledge",
}

function ModelPill({ modelUniqueId }: { modelUniqueId: string }) {
  const [, ...slugParts] = modelUniqueId.split(":")
  const slug = slugParts.join(":") || modelUniqueId
  const connectionId = modelUniqueId.includes(":") ? modelUniqueId.split(":")[0] : null

  const [open, setOpen] = useState(false)
  // Resolve the model through the unified enriched-models hub so that
  // premium-provider slugs (e.g. ``mistral``, ``xai``) dispatch to the
  // providers API — a raw ``listConnectionModels`` call 404s for those.
  const { findByUniqueId } = useEnrichedModels()
  const model = findByUniqueId(modelUniqueId)

  return (
    <span
      className="relative hidden lg:inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span className="rounded-full border border-gold/20 bg-gold/5 px-2.5 py-0.5 font-mono text-[11px] text-gold cursor-default">
        {connectionId ? `${connectionId}/${slug}` : slug}
      </span>
      {open && model && (
        <div
          role="tooltip"
          className="absolute left-0 top-full mt-2 z-50 w-72 rounded-md border border-gold/25 bg-[#0b0a08] lg:bg-[#0b0a08]/95 lg:backdrop-blur-sm shadow-sm lg:shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2.5 text-[12px] font-mono leading-relaxed"
        >
          <ModelTooltipRow label="Provider" value={model.connection_display_name} />
          <ModelTooltipRow label="Model" value={model.model_id} />
          {model.parameter_count && (
            <ModelTooltipRow label="Size" value={model.parameter_count} />
          )}
          {model.quantisation_level && (
            <ModelTooltipRow label="Quant" value={model.quantisation_level} />
          )}
          {model.context_window > 0 && (
            <ModelTooltipRow
              label="Context"
              value={`${model.context_window.toLocaleString()} tokens`}
            />
          )}
        </div>
      )}
    </span>
  )
}

function ModelTooltipRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-white/40">{label}</span>
      <span className="truncate text-white/85">{value}</span>
    </div>
  )
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
  /**
   * Forwarded from `AppLayout`. On mobile the Provider/Jobs/Live pills are
   * hidden; the burger instead surfaces a small red dot when there is an
   * API-key issue so the user still notices it.
   */
  hasApiKeyProblem?: boolean
}

/**
 * Burger button shown only below `lg`. Toggles the off-canvas sidebar drawer.
 */
function BurgerButton({ hasProblem }: { hasProblem: boolean }) {
  const drawerOpen = useDrawerStore((s) => s.sidebarOpen)
  const toggle = useDrawerStore((s) => s.toggle)
  const label = drawerOpen ? "Close navigation" : "Open navigation"
  return (
    <button
      type="button"
      onClick={toggle}
      title={label}
      aria-label={label}
      aria-expanded={drawerOpen}
      className="relative flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/8 hover:text-white/90 lg:hidden"
    >
      {drawerOpen ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      )}
      {hasProblem && (
        <span
          aria-hidden="true"
          className="absolute right-1 top-1 h-2 w-2 rounded-full bg-red-500 ring-2 ring-surface"
        />
      )}
    </button>
  )
}

export function Topbar({ personas, onOpenPersonaOverlay, hasApiKeyProblem = false }: TopbarProps) {
  // TODO Phase 8: surface the active connection's display name alongside
  // the model slug (replaces the old provider-credential lookup).
  const wsStatus = useEventStore((s) => s.status)
  const navigate = useNavigate()
  const location = useLocation()
  const [showAvatar, setShowAvatar] = useState(false)

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")

  const isLive = wsStatus === "connected"

  if (chatMatch) {
    const { personaId } = chatMatch.params
    const persona = personas.find((p) => p.id === personaId)
    const chakra = persona ? CHAKRA_PALETTE[persona.colour_scheme] : null
    const hasAvatar = !!persona?.profile_image

    return (
      <header className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/6 bg-surface px-4">
        <BurgerButton hasProblem={hasApiKeyProblem} />
        {persona && (
          <div className="flex min-w-0 items-center gap-1">
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
                className="flex min-w-0 items-center gap-2 rounded-full border border-white/8 bg-white/5 px-3 py-1 text-[13px] font-medium text-white/75 transition-colors hover:bg-white/8"
              >
                <span className="h-2 w-2 flex-shrink-0 rounded-full bg-purple" />
                <span className="min-w-0 truncate">{persona.name}</span>
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
        {persona && persona.model_unique_id && (
          <ModelPill modelUniqueId={persona.model_unique_id} />
        )}
        <div className="ml-auto hidden flex-shrink-0 items-center gap-1.5 lg:flex">
          <JobsPill personas={personas} />
          <LivePill isLive={isLive} wsStatus={wsStatus} />
        </div>
      </header>
    )
  }

  const path = location.pathname
  const title = SECTION_TITLES[path] ?? ""

  return (
    <header className="flex h-[50px] flex-shrink-0 items-center gap-4 border-b border-white/6 bg-surface px-4">
      <BurgerButton hasProblem={hasApiKeyProblem} />
      <span className="min-w-0 truncate text-[13px] font-semibold text-white/60">{title}</span>
      <div className="ml-auto hidden items-center gap-2 lg:flex">
        <JobsPill personas={personas} />
        <LivePill isLive={isLive} wsStatus={wsStatus} />
      </div>
    </header>
  )
}
