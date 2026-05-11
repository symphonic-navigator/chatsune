import { Sheet } from '../../core/components/Sheet'
import type { ConversationItemDto } from '../../core/api/chatGptImportApi'

interface Props {
  isOpen: boolean
  onCancel: () => void
  onConfirm: () => void
  selectedConvs: ConversationItemDto[]
  personaName: string
  currentPersonaId: string
}

export function ImportConfirmDialog({
  isOpen,
  onCancel,
  onConfirm,
  selectedConvs,
  personaName,
  currentPersonaId,
}: Props) {
  const otherPersonaCount = selectedConvs.filter((c) =>
    c.imports.some((i) => i.persona_id !== currentPersonaId),
  ).length

  return (
    <Sheet
      isOpen={isOpen}
      onClose={onCancel}
      size="md"
      ariaLabel="Confirm import"
      className="bg-[#0f0d16] text-white"
    >
      <div className="p-6">
        <h2 className="text-xl font-semibold text-white mb-3">Confirm import</h2>
        <p className="text-white/80 mb-4">
          Import <strong>{selectedConvs.length}</strong> conversation
          {selectedConvs.length === 1 ? '' : 's'} into &ldquo;{personaName}&rdquo;?
        </p>
        <ul className="text-sm text-white/70 mb-4 max-h-40 overflow-y-auto list-disc pl-5">
          {selectedConvs.map((c) => (
            <li key={c.chatgpt_conversation_id} className="truncate">
              {c.title || '(untitled)'}
            </li>
          ))}
        </ul>
        {otherPersonaCount > 0 && (
          <p className="text-xs text-white/60 mb-4 italic">
            {otherPersonaCount} of these {otherPersonaCount === 1 ? 'is' : 'are'} already
            imported into other personas — a new session in
            &ldquo;{personaName}&rdquo; will be created in addition.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium"
          >
            Import
          </button>
        </div>
      </div>
    </Sheet>
  )
}
