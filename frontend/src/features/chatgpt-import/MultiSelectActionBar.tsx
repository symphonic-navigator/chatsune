import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

interface Props {
  onImportClick: () => void
  personaName: string
}

export function MultiSelectActionBar({ onImportClick, personaName }: Props) {
  const selectedCount = useChatGptImportStore((s) => s.selectedConversationIds.size)
  const clearSelection = useChatGptImportStore((s) => s.clearSelection)

  if (selectedCount === 0) return null

  return (
    <div className="sticky bottom-0 left-0 right-0 bg-[#0f0d16] border-t border-white/10 px-4 py-3 flex items-center justify-between z-10">
      <span className="text-white/80 text-sm">{selectedCount} selected</span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onImportClick}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium text-sm"
        >
          Import into &ldquo;{personaName}&rdquo;
        </button>
        <button
          type="button"
          onClick={clearSelection}
          aria-label="Clear selection"
          className="px-3 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
        >
          ×
        </button>
      </div>
    </div>
  )
}
