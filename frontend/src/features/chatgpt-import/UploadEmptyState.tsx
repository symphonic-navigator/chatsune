import { useRef } from 'react'

interface Props {
  onFileSelected: (file: File) => void
  isUploading: boolean
  uploadProgress: number | null
}

export function UploadEmptyState({ onFileSelected, isUploading, uploadProgress }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  const onClick = () => inputRef.current?.click()
  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onFileSelected(file)
    // Reset the input so the same file can be reselected if the user dismisses
    // the replace dialog and immediately picks the same file again.
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div className="p-8 text-center">
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        onChange={onChange}
        className="hidden"
      />
      <button
        type="button"
        onClick={onClick}
        disabled={isUploading}
        className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-white font-medium"
      >
        {isUploading
          ? `Uploading… ${uploadProgress != null ? `${Math.round(uploadProgress / 1024 / 1024)} MB` : ''}`
          : 'Upload ChatGPT export'}
      </button>
      <p className="mt-6 text-sm text-white/70 max-w-md mx-auto">
        Upload your ChatGPT export <code className="font-mono">conversations.json</code>.
        You can then import individual or multiple conversations into this persona
        as native Chatsune sessions.
      </p>
      <ul className="mt-4 text-xs text-white/50 max-w-md mx-auto text-left list-disc pl-5 space-y-0.5">
        <li>Retained on the server for 14 days</li>
        <li>Retention resets on every import action</li>
        <li>The upload list is shared across all your personas</li>
        <li>Attachments, images and tool outputs are not imported</li>
      </ul>
    </div>
  )
}
