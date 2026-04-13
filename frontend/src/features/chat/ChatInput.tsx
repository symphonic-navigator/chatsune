import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type ChangeEvent, type ClipboardEvent, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'
import { useViewport } from '../../core/hooks/useViewport'
import { hapticTap } from '../../core/utils/haptics'
import { VoiceButton } from '../voice/components/VoiceButton'
import type { PipelinePhase } from '../voice/types'

const LONG_PASTE_THRESHOLD = 500

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
  voiceEnabled?: boolean
  voicePhase?: PipelinePhase
  volumeLevel?: number
  onMicPress?: () => void
  onMicRelease?: () => void
  onStopRecording?: () => void
}

export interface ChatInputHandle {
  focus: () => void
  /** Open the native camera picker (mobile). On desktop the OS file picker
   *  opens instead because the `capture` attribute is ignored there. */
  openCamera: () => void
  /** Open the native file picker for attaching files. */
  openFilePicker: () => void
}

export const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  { onSend, onCancel, onFilesSelected, onToggleBrowser, isStreaming, disabled, hasPendingUploads, toolBar, attachmentStrip, voiceEnabled, voicePhase, volumeLevel, onMicPress, onMicRelease, onStopRecording }, ref,
) {
  const { isMobile } = useViewport()
  const [text, setText] = useState('')
  const [pendingPaste, setPendingPaste] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cameraInputRef = useRef<HTMLInputElement>(null)

  useImperativeHandle(ref, () => ({
    focus: () => textareaRef.current?.focus(),
    openCamera: () => cameraInputRef.current?.click(),
    openFilePicker: () => fileInputRef.current?.click(),
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
    setPendingPaste(null)
    hapticTap()
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
      if (pastedText.length >= LONG_PASTE_THRESHOLD) {
        setPendingPaste(pastedText)
      }
    },
    [onFilesSelected],
  )

  const handleKeepAsText = useCallback(() => {
    setPendingPaste(null)
  }, [])

  const handleAttachAsFile = useCallback(() => {
    if (!pendingPaste) return
    // Remove the pasted text from the input — it was already inserted by the browser
    setText((prev) => {
      const idx = prev.lastIndexOf(pendingPaste)
      if (idx === -1) return prev
      return prev.slice(0, idx) + prev.slice(idx + pendingPaste.length)
    })
    const blob = new Blob([pendingPaste], { type: 'text/plain' })
    const file = new File([blob], 'pasted-text.txt', { type: 'text/plain' })
    onFilesSelected([file])
    setPendingPaste(null)
  }, [pendingPaste, onFilesSelected])

  const handleTextChange = useCallback((e: ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    // Dismiss the paste confirmation if the user continues typing
    if (pendingPaste) setPendingPaste(null)
  }, [pendingPaste])

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
      if (e.key === 'Enter' && !e.shiftKey && !isMobile) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend, isMobile],
  )

  return (
    <div
      className="sticky bottom-0 z-10 border-t border-white/6 bg-surface px-4 py-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] lg:static lg:pb-3"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <input ref={fileInputRef} type="file" multiple accept="*/*" className="hidden"
        onChange={(e) => { if (e.target.files?.length) { onFilesSelected(Array.from(e.target.files)); e.target.value = '' } }} />
      {/* Camera input: `capture="environment"` hints mobile browsers to open
          the rear camera directly. Desktop browsers ignore the attribute and
          fall back to the normal file picker — which is why this input is
          only reachable via the mobile tool tray. */}
      <input ref={cameraInputRef} type="file" accept="image/*" capture="environment" className="hidden"
        onChange={(e) => { if (e.target.files?.length) { onFilesSelected(Array.from(e.target.files)); e.target.value = '' } }} />
      {toolBar && (
        <div className="mx-auto mb-2 max-w-3xl">{toolBar}</div>
      )}
      {attachmentStrip && (
        <div className="mx-auto mb-2 max-w-3xl">{attachmentStrip}</div>
      )}
      {pendingPaste && (
        <div className="mx-auto mb-2 max-w-3xl rounded-lg border border-white/8 bg-white/5 px-3 py-2">
          <p className="mb-2 text-sm text-white/60">
            Pasted text is quite long ({pendingPaste.length.toLocaleString()} characters). What would you like to do?
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleKeepAsText}
              className="rounded-md border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70 transition-colors hover:bg-white/10 hover:text-white/90"
            >
              Keep as text
            </button>
            <button
              type="button"
              onClick={handleAttachAsFile}
              className="rounded-md border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70 transition-colors hover:bg-white/10 hover:text-white/90"
            >
              Attach as file
            </button>
          </div>
        </div>
      )}
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming || disabled}
          className="hidden h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-white/60 transition-colors hover:text-white/85 disabled:opacity-30 lg:flex"
          title="Attach file"
          aria-label="Attach file"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M7.5 2C5 2 3 4 3 6.5V11C3 13.5 5 15.5 7.5 15.5C10 15.5 12 13.5 12 11V5.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
        </button>
        <button
          type="button"
          onClick={onToggleBrowser}
          disabled={isStreaming || disabled}
          className="hidden h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-white/60 transition-colors hover:text-white/85 disabled:opacity-30 lg:flex"
          title="Browse uploads"
          aria-label="Browse uploads"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 4.5V12.5C2 13.05 2.45 13.5 3 13.5H13C13.55 13.5 14 13.05 14 12.5V6.5C14 5.95 13.55 5.5 13 5.5H8L6.5 3.5H3C2.45 3.5 2 3.95 2 4.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
          </svg>
        </button>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Type a message..."
          disabled={isStreaming || disabled}
          rows={1}
          className="chat-text max-h-[40vh] flex-1 resize-none overflow-y-auto rounded-lg border border-white/8 bg-white/4 px-3 py-2 text-white/90 placeholder-white/55 outline-none transition-colors focus:border-white/15 focus:bg-white/6 disabled:opacity-40 lg:max-h-none lg:overflow-hidden"
        />
        {voiceEnabled ? (
          <VoiceButton
            phase={voicePhase ?? 'idle'}
            hasText={!!text.trim()}
            isStreaming={isStreaming}
            disabled={disabled}
            hasPendingUploads={hasPendingUploads}
            volumeLevel={volumeLevel ?? 0}
            onSend={handleSend}
            onCancel={onCancel}
            onMicPress={onMicPress ?? (() => {})}
            onMicRelease={onMicRelease ?? (() => {})}
            onStopRecording={onStopRecording ?? (() => {})}
          />
        ) : (
          <>
            {isStreaming ? (
              <button
                type="button"
                data-testid="cancel-button"
                onClick={onCancel}
                title="Cancel response"
                aria-label="Cancel response"
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
                title="Send message"
                aria-label="Send message"
                className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/6 text-white/60 transition-colors hover:bg-white/10 hover:text-white/85 disabled:opacity-30 disabled:hover:bg-white/6"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M2 14L14.5 8L2 2V6.5L10 8L2 9.5V14Z" fill="currentColor" />
                </svg>
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
})
