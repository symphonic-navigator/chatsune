import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuthStore } from "../../../core/store/authStore"
import { useAuth } from "../../../core/hooks/useAuth"
import { NavRow } from "./NavRow"
import { PersonaItem } from "./PersonaItem"
import { HistoryItem } from "./HistoryItem"
import type { PersonaDto } from "../../../core/types/persona"
import type { ChatSessionDto } from "../../../core/api/chat"

interface SidebarProps {
  personas: PersonaDto[]
  sessions: ChatSessionDto[]
  activePersonaId: string | null
  activeSessionId: string | null
}

export function Sidebar({ personas, sessions, activePersonaId, activeSessionId }: SidebarProps) {
  const user = useAuthStore((s) => s.user)
  const { logout } = useAuth()
  const navigate = useNavigate()

  const isAdmin = user?.role === "admin" || user?.role === "master_admin"

  const [projectsOpen, setProjectsOpen] = useState(() => {
    return localStorage.getItem("chatsune_projects_open") === "true"
  })

  function toggleProjects() {
    const next = !projectsOpen
    setProjectsOpen(next)
    localStorage.setItem("chatsune_projects_open", String(next))
  }

  function handlePersonaSelect(persona: PersonaDto) {
    navigate(`/chat/${persona.id}`)
  }

  function handleNewChat(persona: PersonaDto) {
    navigate(`/chat/${persona.id}?new=1`)
  }

  function handleSessionClick(session: ChatSessionDto) {
    navigate(`/chat/${session.persona_id}/${session.id}`)
  }

  return (
    <aside className="flex h-full w-[232px] flex-shrink-0 flex-col border-r border-white/6 bg-base">

      {/* Logo */}
      <div className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/5 px-3.5">
        <span className="text-[17px]">⬡</span>
        <span className="text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
      </div>

      {/* Admin banner — admins only */}
      {isAdmin && (
        <button
          type="button"
          onClick={() => navigate("/admin")}
          className="mx-2 mt-2 flex items-center gap-2 rounded-lg border border-gold/16 bg-gold/7 px-2.5 py-1.5 transition-colors hover:bg-gold/12"
        >
          <span className="text-[12px]">✦</span>
          <span className="flex-1 text-left text-[12px] font-bold uppercase tracking-widest text-gold">Admin</span>
          <span className="text-[11px] text-gold/50">›</span>
        </button>
      )}

      {/* CHAT */}
      <div className="mt-1.5 flex-shrink-0">
        <NavRow icon="◈" label="Chat" onClick={() => navigate("/personas")} />
        <div className="mt-0.5">
          {personas.map((p) => (
            <PersonaItem
              key={p.id}
              persona={p}
              isActive={p.id === activePersonaId}
              onSelect={handlePersonaSelect}
              onNewChat={handleNewChat}
              onNewIncognitoChat={(persona) => navigate(`/chat/${persona.id}?incognito=1`)}
              onEdit={(persona) => navigate(`/personas?edit=${persona.id}`)}
              onUnpin={() => {
                // Phase 2 — requires pin field in backend
              }}
            />
          ))}
          {personas.length === 0 && (
            <p className="px-4 py-1 text-[12px] text-white/20">No personas yet</p>
          )}
        </div>
      </div>

      <div className="mx-2 my-1.5 h-px bg-white/4" />

      {/* Shared scroll zone: Projects + History */}
      <div className="min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/8">

        {/* PROJECTS */}
        <NavRow
          icon="◫"
          label="Projects"
          onClick={() => navigate("/projects")}
          actions={
            <>
              <button
                type="button"
                className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/20 transition-colors hover:bg-white/8 hover:text-white/55"
                onClick={() => navigate("/projects?search=1")}
                aria-label="Search projects"
              >
                🔍
              </button>
              <button
                type="button"
                className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/20 transition-colors hover:bg-white/8 hover:text-white/55"
                onClick={toggleProjects}
                aria-label={projectsOpen ? "Collapse projects" : "Expand projects"}
              >
                {projectsOpen ? "∨" : "›"}
              </button>
            </>
          }
        />

        {projectsOpen && (
          <p className="mx-3 py-1 text-[12px] text-white/20">No projects yet</p>
        )}

        <div className="mx-2 my-1 h-px bg-white/4" />

        {/* HISTORY */}
        <NavRow
          icon="◷"
          label="History"
          onClick={() => navigate("/history")}
          actions={
            <button
              type="button"
              className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/20 transition-colors hover:bg-white/8 hover:text-white/55"
              onClick={() => navigate("/history?search=1")}
              aria-label="Search history"
            >
              🔍
            </button>
          }
        />

        <div className="mt-0.5 pb-2">
          {sessions.map((s) => (
            <HistoryItem
              key={s.id}
              session={s}
              isPinned={false}
              isActive={s.id === activeSessionId}
              onClick={handleSessionClick}
            />
          ))}
          {sessions.length === 0 && (
            <p className="px-4 py-1 text-[12px] text-white/20">No history yet</p>
          )}
        </div>

      </div>

      {/* Bottom */}
      <div className="flex-shrink-0 border-t border-white/5">
        <NavRow icon="🧠" label="Knowledge" onClick={() => navigate("/knowledge")} />

        {/* User row — entire area is the menu trigger (logout for now, full menu is Phase 2) */}
        <button
          type="button"
          onClick={() => logout()}
          className="flex w-full items-center gap-2.5 px-3 py-2.5 transition-colors hover:bg-white/4"
          title="Click to log out (settings menu coming soon)"
        >
          <div className="flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
            {user?.display_name?.charAt(0).toUpperCase() ?? user?.username?.charAt(0).toUpperCase() ?? "?"}
          </div>
          <div className="text-left">
            <p className="text-[13px] font-medium text-white/65">{user?.display_name || user?.username}</p>
            <p className="text-[10px] text-white/22">{user?.role}</p>
          </div>
        </button>
      </div>

    </aside>
  )
}
