import { useLocation, useMatch, useNavigate } from "react-router-dom"
import { useEventStore } from "../../../core/store/eventStore"
import type { PersonaDto } from "../../../core/types/persona"

const SECTION_TITLES: Record<string, string> = {
  "/personas": "Personas",
  "/projects": "Projects",
  "/history": "History",
  "/knowledge": "Knowledge",
}

const ADMIN_TABS = ["Users", "Models", "System"]

interface TopbarProps {
  personas: PersonaDto[]
}

export function Topbar({ personas }: TopbarProps) {
  const wsStatus = useEventStore((s) => s.status)
  const navigate = useNavigate()
  const location = useLocation()

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const adminMatch = useMatch("/admin/*")

  const isLive = wsStatus === "connected"

  const LivePill = () => (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px]
        ${isLive ? "border-white/7 bg-white/4 text-white/35" : "border-white/5 bg-white/2 text-white/20"}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-live" : "bg-white/20"}`} />
      {wsStatus}
    </span>
  )

  if (chatMatch) {
    const { personaId } = chatMatch.params
    const persona = personas.find((p) => p.id === personaId)

    return (
      <header className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/6 bg-surface px-4">
        {persona && (
          <button
            type="button"
            onClick={() => navigate("/personas")}
            className="flex items-center gap-2 rounded-full border border-white/8 bg-white/5 px-3 py-1 text-[13px] font-medium text-white/75 transition-colors hover:bg-white/8"
          >
            <span className="h-2 w-2 rounded-full bg-purple" />
            {persona.name}
          </button>
        )}
        <span className="text-white/15">/</span>
        <span className="max-w-[260px] truncate text-[13px] text-white/32">
          {chatMatch.params.sessionId ? "Continued session" : "New chat"}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {persona && (
            <span className="rounded-full border border-gold/20 bg-gold/5 px-2.5 py-0.5 font-mono text-[11px] text-gold">
              {persona.model_unique_id.split(":")[1] ?? persona.model_unique_id}
            </span>
          )}
          <LivePill />
        </div>
      </header>
    )
  }

  if (adminMatch) {
    const activeTab = location.pathname.split('/')[2] ?? 'users'

    return (
      <header className="flex h-[50px] flex-shrink-0 items-stretch border-b border-white/6 bg-surface px-4">
        <span className="flex items-center pr-4 text-[13px] font-semibold text-white/60">Admin</span>
        <div className="flex">
          {ADMIN_TABS.map((tab) => {
            const isActive = activeTab === tab.toLowerCase()
            return (
              <button
                key={tab}
                type="button"
                onClick={() => navigate(`/admin/${tab.toLowerCase()}`)}
                className={[
                  'px-3 text-[13px] border-b-2 -mb-px cursor-pointer transition-colors',
                  isActive
                    ? 'border-gold text-gold'
                    : 'border-transparent text-white/40 hover:text-white/70',
                ].join(' ')}
              >
                {tab}
              </button>
            )
          })}
        </div>
        <div className="ml-auto flex items-center">
          <LivePill />
        </div>
      </header>
    )
  }

  const path = location.pathname
  const title = SECTION_TITLES[path] ?? ""

  return (
    <header className="flex h-[50px] flex-shrink-0 items-center gap-4 border-b border-white/6 bg-surface px-4">
      <span className="text-[13px] font-semibold text-white/60">{title}</span>
      <div className="ml-auto">
        <LivePill />
      </div>
    </header>
  )
}
