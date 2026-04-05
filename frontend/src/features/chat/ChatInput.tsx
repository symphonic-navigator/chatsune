import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

interface ChatInputProps {
  onSend: (text: string) => void
  onCancel: () => void
  isStreaming: boolean
  disabled: boolean
  toolBar?: ReactNode
}

export interface ChatInputHandle {
  focus: () => void
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, onCancel, isStreaming, disabled, toolBar }, ref,
) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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
    if (!trimmed || isStreaming || disabled) return
    onSend(trimmed)
    setText('')
  }, [text, isStreaming, disabled, onSend])

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
    <div className="border-t border-white/6 bg-surface px-4 py-3">
      {toolBar && (
        <div className="mx-auto mb-2 max-w-3xl">{toolBar}</div>
      )}
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
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
            disabled={!text.trim() || disabled}
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
