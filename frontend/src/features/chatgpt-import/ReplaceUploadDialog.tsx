import { Sheet } from '../../core/components/Sheet'

interface Props {
  isOpen: boolean
  onCancel: () => void
  onConfirm: () => void
  currentFilename: string
  currentConversationCount: number
}

export function ReplaceUploadDialog({
  isOpen,
  onCancel,
  onConfirm,
  currentFilename,
  currentConversationCount,
}: Props) {
  return (
    <Sheet
      isOpen={isOpen}
      onClose={onCancel}
      size="md"
      ariaLabel="Replace active file"
      className="bg-[#0f0d16] text-white"
    >
      <div className="p-6">
        <h2 className="text-xl font-semibold text-white mb-3">
          Replace active upload?
        </h2>
        <p className="text-white/80 mb-3">
          There is already an active upload
          {currentFilename ? (
            <>
              {' '}
              (<code className="font-mono text-sm">{currentFilename}</code>,{' '}
              {currentConversationCount} conversations)
            </>
          ) : null}
          .
        </p>
        <p className="text-white/70 mb-3">
          If you upload a new file the previous one is deleted along with any
          not-yet-imported conversations.
        </p>
        <p className="text-white/50 mb-4 text-xs italic">
          Already-imported sessions remain untouched.
        </p>
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
            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded font-medium"
          >
            Replace
          </button>
        </div>
      </div>
    </Sheet>
  )
}
