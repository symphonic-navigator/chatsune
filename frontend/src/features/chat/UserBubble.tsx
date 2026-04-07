import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { AttachmentRefDto, VisionDescriptionSnapshot } from '../../core/api/chat'
import type { LiveVisionDescription } from '../../core/store/chatStore'
import { AttachmentChip } from './AttachmentChip'
import { VisionDescriptionBlock } from './VisionDescriptionBlock'

interface UserBubbleProps {
  content: string
  attachments?: AttachmentRefDto[] | null
  visionDescriptionsUsed?: VisionDescriptionSnapshot[] | null
  liveVisionDescriptions?: Record<string, LiveVisionDescription>
  onEdit: (newContent: string) => void
  isEditable: boolean
  isBookmarked?: boolean
  onBookmark?: () => void
}

export function UserBubble({ content, attachments, visionDescriptionsUsed, liveVisionDescriptions, onEdit, isEditable, isBookmarked, onBookmark }: UserBubbleProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editText, setEditText] = useState(content)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!isEditing || !textareaRef.current) return
    const el = textareaRef.current
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  }, [isEditing, editText])

  const startEdit = useCallback(() => { setEditText(content); setIsEditing(true) }, [content])
  const cancelEdit = useCallback(() => { setIsEditing(false) }, [])
  const submitEdit = useCallback(() => {
    const trimmed = editText.trim()
    if (!trimmed) return
    setIsEditing(false)
    if (trimmed !== content) onEdit(trimmed)
  }, [editText, content, onEdit])

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitEdit() }
    if (e.key === 'Escape') cancelEdit()
  }, [submitEdit, cancelEdit])

  if (isEditing) {
    return (
      <div data-testid="user-bubble" className="flex justify-end animate-message-entrance">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm border border-white/10 bg-white/8 px-4 py-2.5">
          <textarea ref={textareaRef} value={editText} onChange={(e) => setEditText(e.target.value)} onKeyDown={handleKeyDown} rows={1}
            className="chat-text w-full min-w-[200px] resize-none bg-transparent text-white/90 outline-none" />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" data-testid="edit-cancel" onClick={cancelEdit}
              className="rounded px-2.5 py-1 text-[12px] text-white/40 transition-colors hover:text-white/60">Cancel</button>
            <button type="button" data-testid="edit-submit" onClick={submitEdit}
              disabled={editText.trim() === content || !editText.trim()}
              className="rounded bg-white/10 px-2.5 py-1 text-[12px] text-white/70 transition-colors hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed">Save & resend</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div data-testid="user-bubble" className="flex justify-end animate-message-entrance">
      <div className="max-w-[80%]">
        <div className="rounded-2xl rounded-tr-sm bg-white/8 px-4 py-2.5">
          <p className="chat-text whitespace-pre-wrap text-white/90">{content}</p>
          {attachments && attachments.length > 0 && (
            <div className="mt-1.5 flex flex-col gap-1.5">
              {attachments.map((att) => {
                const isImage = att.media_type.startsWith('image/')
                const persisted = visionDescriptionsUsed?.find((s) => s.file_id === att.file_id)
                const live = liveVisionDescriptions?.[att.file_id]
                const visionState: LiveVisionDescription | null = live
                  ? live
                  : persisted
                    ? {
                        file_id: persisted.file_id,
                        display_name: persisted.display_name,
                        model_id: persisted.model_id,
                        status: 'success' as const,
                        text: persisted.text,
                        error: null,
                      }
                    : null
                return (
                  <div key={att.file_id} className="flex flex-col">
                    <AttachmentChip attachment={att} />
                    {isImage && visionState && (
                      <VisionDescriptionBlock
                        status={visionState.status}
                        modelId={visionState.model_id}
                        text={visionState.text}
                        error={visionState.error}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {isEditable && (
            <div className="mt-2.5 flex gap-3 border-t border-white/6 pt-2">
              <button type="button" data-testid="edit-button" onClick={startEdit}
                className="flex items-center gap-1 text-[11px] text-white/25 transition-colors hover:text-white/50"
                title="Edit message">
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                  <path d="M10.5 1.5L12.5 3.5L4 12H2V10L10.5 1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Edit
              </button>
              {onBookmark && (
                <button type="button" onClick={onBookmark}
                  className={`flex items-center gap-1 text-[11px] transition-colors ${isBookmarked ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
                  title={isBookmarked ? 'Bookmarked' : 'Bookmark'}>
                  <svg width="13" height="13" viewBox="0 0 14 14" fill={isBookmarked ? 'currentColor' : 'none'}>
                    <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                  </svg>
                  {isBookmarked ? 'Bookmarked' : 'Bookmark'}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
