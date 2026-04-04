import type { ChatSessionDto } from "../../../core/api/chat"

function formatSessionDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString("de-DE", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface HistoryItemProps {
  session: ChatSessionDto
  isPinned: boolean
  isActive: boolean
  onClick: (session: ChatSessionDto) => void
}

export function HistoryItem({ session, isPinned, isActive, onClick }: HistoryItemProps) {
  return (
    <div
      className={`mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1 text-[12px] transition-colors
        ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}`}
      onClick={() => onClick(session)}
    >
      {isPinned && <span className="flex-shrink-0 text-[11px]">📌</span>}
      <div className="flex flex-col gap-0.5 overflow-hidden">
        <span className="truncate text-[13px]">
          {session.title ?? formatSessionDate(session.updated_at)}
        </span>
        {session.title && (
          <span className="truncate text-[11px] opacity-50">
            {formatSessionDate(session.updated_at)}
          </span>
        )}
      </div>
    </div>
  )
}
