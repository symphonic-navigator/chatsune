import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'

interface ChatInputProps {
  onSend: (text: string) => void
  onCancel: () => void
  onFilesSelected: (files: File[]) => void
  onToggleBrowser: () => void
  isStreaming: boolean
  disabled: boolean
  hasPendingUploads: boolean
  toolBar?: ReactNode
  attachmentStrip?: ReactNode
}

export interface ChatInputHandle {
  focus: () => void
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, onCancel, onFilesSelected, onToggleBrowser, isStreaming, disabled, hasPendingUploads, toolBar, attachmentStrip }, ref,
) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useImperativeHandle(ref, () => ({
    focus: () => textareaRef.current?.focus(),
  }))

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [text])

  useEffect(() => {
    if (!isStreaming) textareaRef.current?.focus()
  }, [isStreaming])

  const handleSend = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed || isStreaming || disabled || hasPendingUploads) return
    onSend(trimmed)
    setText('')
  }, [text, isStreaming, disabled, hasPendingUploads, onSend])

  const handlePaste = useCallback(
    (e: ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'))
      if (files.length > 0) {
        e.preventDefault()
        onFilesSelected(files)
        return
      }
      const pastedText = e.clipboardData.getData('text')
      if (pastedText.length >= 500) {
        e.preventDefault()
        const blob = new Blob([pastedText], { type: 'text/plain' })
        const file = new File([blob], 'pasted-text.txt', { type: 'text/plain' })
        onFilesSelected([file])
      }
    },
    [onFilesSelected],
  )

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
  }, [])

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      const files = Array.from(e.dataTransfer.files)
      if (files.length > 0) onFilesSelected(files)
    },
    [onFilesSelected],
  )

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  return (
    <div className="border-t border-white/6 bg-surface px-4 py-3" onDragOver={handleDragOver} onDrop={handleDrop}>
      <input ref={fileInputRef} type="file" multiple accept="*/*" className="hidden"
        onChange={(e) => { if (e.target.files?.length) { onFilesSelected(Array.from(e.target.files)); e.target.value = '' } }} />
      {toolBar && (
        <div className="mx-auto mb-2 max-w-3xl">{toolBar}</div>
      )}
      {attachmentStrip && (
        <div className="mx-auto mb-2 max-w-3xl">{attachmentStrip}</div>
      )}
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming || disabled}
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-white/30 transition-colors hover:text-white/60 disabled:opacity-30"
          title="Attach file"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M7.5 2C5 2 3 4 3 6.5V11C3 13.5 5 15.5 7.5 15.5C10 15.5 12 13.5 12 11V5.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
        </button>
        <button
          type="button"
          onClick={onToggleBrowser}
          disabled={isStreaming || disabled}
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-white/30 transition-colors hover:text-white/60 disabled:opacity-30"
          title="Browse uploads"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 4.5V12.5C2 13.05 2.45 13.5 3 13.5H13C13.55 13.5 14 13.05 14 12.5V6.5C14 5.95 13.55 5.5 13 5.5H8L6.5 3.5H3C2.45 3.5 2 3.95 2 4.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
          </svg>
        </button>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Type a message..."
          disabled={isStreaming || disabled}
          rows={1}
          className="chat-text flex-1 resize-none overflow-hidden rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-white/90 placeholder-white/20 outline-none transition-colors focus:border-white/15 focus:bg-white/6 disabled:opacity-40"
        />
        {isStreaming ? (
          <button
            type="button"
            data-testid="cancel-button"
            onClick={onCancel}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 transition-colors hover:bg-red-500/20"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
            </svg>
          </button>
        ) : (
          <button
            type="button"
            data-testid="send-button"
            onClick={handleSend}
            disabled={!text.trim() || disabled || hasPendingUploads}
            className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-white/50 transition-colors hover:bg-white/10 hover:text-white/70 disabled:opacity-30 disabled:hover:bg-white/6"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M2 14L14.5 8L2 2V6.5L10 8L2 9.5V14Z" fill="currentColor" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
})
