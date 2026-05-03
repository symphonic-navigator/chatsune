import type { PersonaDto } from '../../../core/types/persona'
import { NewChatRow } from './NewChatRow'

interface ActionBlockProps {
  personas: PersonaDto[]
  showContinue: boolean
  onCloseModal: () => void
  onNewIncognitoChat: () => void
  onContinue: () => void
}

/**
 * Top action block of the sidebar: New Chat (with persona picker),
 * New Incognito Chat, and the conditional Continue row.
 */
export function ActionBlock({
  personas,
  showContinue,
  onCloseModal,
  onNewIncognitoChat,
  onContinue,
}: ActionBlockProps) {
  return (
    <div className="flex-shrink-0 border-b border-white/5 pb-1">
      <NewChatRow personas={personas} onCloseModal={onCloseModal} />

      <button
        type="button"
        onClick={onNewIncognitoChat}
        className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/5"
      >
        <span className="text-[14px]">🕶️</span>
        <span className="flex-1 text-[12px] font-medium uppercase tracking-wider text-white/70 group-hover:text-white/90">
          New Incognito Chat
        </span>
        <span className="text-[10px] text-white/40">›</span>
      </button>

      {showContinue && (
        <button
          type="button"
          onClick={onContinue}
          className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-white/5"
        >
          <span className="text-[12px] text-white/60 group-hover:text-white/80">▶️</span>
          <span className="flex-1 text-[12px] text-white/60 group-hover:text-white/85">Continue</span>
          <span className="text-[10px] text-white/40">›</span>
        </button>
      )}
    </div>
  )
}
