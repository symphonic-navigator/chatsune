import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useChatSessions } from '../../../core/hooks/useChatSessions'
import { usePersonas } from '../../../core/hooks/usePersonas'
import type { ChatSessionDto } from '../../../core/api/chat'

interface HistoryTabProps {
  onClose: () => void
}

function getDateGroup(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const today = now.toDateString()
  const yesterday = new Date(now.getTime() - 86_400_000).toDateString()
  const weekAgo = new Date(now.getTime() - 7 * 86_400_000)
  const monthAgo = new Date(now.getTime() - 30 * 86_400_000)

  if (date.toDateString() === today) return 'Today'
  if (date.toDateString() === yesterday) return 'Yesterday'
  if (date > weekAgo) return 'This Week'
  if (date > monthAgo) return 'This Month'
  return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

function groupSessions(sessions: ChatSessionDto[]): [string, ChatSessionDto[]][] {
  const map = new Map<string, ChatSessionDto[]>()
  for (const s of sessions) {
    const group = getDateGroup(s.updated_at)
    const existing = map.get(group) ?? []
    map.set(group, [...existing, s])
  }
  return Array.from(map.entries())
}

export function HistoryTab({ onClose }: HistoryTabProps) {
  const { sessions, isLoading } = useChatSessions()
  const { personas } = usePersonas()
  const [search, setSearch] = useState('')
  const navigate = useNavigate()

  const personaName = (personaId: string): string =>
    personas.find((p) => p.id === personaId)?.name ?? personaId

  const filtered = useMemo(() => {
    if (!search.trim()) return sessions
    const term = search.toLowerCase()
    return sessions.filter(
      (s) =>
        personaName(s.persona_id).toLowerCase().includes(term) ||
        s.id.toLowerCase().includes(term),
    )
  }, [sessions, search, personas])

  const grouped = useMemo(() => groupSessions(filtered), [filtered])

  function handleOpen(session: ChatSessionDto) {
    navigate(`/chat/${session.persona_id}/${session.id}`)
    onClose()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search history..."
          className="w-full bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none focus:border-gold/30 transition-colors font-mono"
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {isLoading && (
          <p className="px-4 py-3 text-[12px] text-white/30 font-mono">Loading...</p>
        )}
        {!isLoading && filtered.length === 0 && (
          <p className="px-4 py-3 text-[12px] text-white/30 font-mono">No sessions found.</p>
        )}
        {grouped.map(([group, groupSessions]) => (
          <div key={group}>
            <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-widest text-white/30 font-mono">
              {group}
            </div>
            {groupSessions.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => handleOpen(s)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors hover:bg-white/4 group"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
                    {personaName(s.persona_id)}
                  </p>
                  <p className="text-[10px] text-white/30 font-mono mt-0.5">
                    {new Date(s.updated_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </div>
                <span className="text-[11px] text-white/20 group-hover:text-gold/50 transition-colors">›</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}
