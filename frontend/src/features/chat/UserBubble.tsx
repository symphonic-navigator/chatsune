import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { AttachmentRefDto } from '../../core/api/chat'
import { AttachmentChip } from './AttachmentChip'

interface UserBubbleProps {
  content: string
  attachments?: AttachmentRefDto[] | null
  onEdit: (newContent: string) => void
  isEditable: boolean
  isBookmarked?: boolean
  onBookmark?: () => void
}

export function UserBubble({ content, attachments, onEdit, isEditable, isBookmarked, onBookmark }: UserBubbleProps) {
  const [isHovered, setIsHovered] = useState(false)
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
              className="rounded bg-white/10 px-2.5 py-1 text-[12px] text-white/70 transition-colors hover:bg-white/15">Save & resend</button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div data-testid="user-bubble" className="group flex justify-end animate-message-entrance"
      onMouseEnter={() => setIsHovered(true)} onMouseLeave={() => setIsHovered(false)}>
      <div className="relative max-w-[80%]">
        {isHovered && isEditable && (
          <div className="absolute -left-8 top-1 flex flex-col gap-1">
            <button type="button" data-testid="edit-button" onClick={startEdit}
              className="rounded p-1 text-white/20 transition-colors hover:text-white/50" title="Edit message">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M10.5 1.5L12.5 3.5L4 12H2V10L10.5 1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {onBookmark && (
              <button type="button" onClick={onBookmark}
                className={`rounded p-1 transition-colors ${isBookmarked ? 'text-gold' : 'text-white/20 hover:text-white/50'}`}
                title={isBookmarked ? 'Bookmarked' : 'Bookmark'}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill={isBookmarked ? 'currentColor' : 'none'}>
                  <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        )}
        <div className="rounded-2xl rounded-tr-sm bg-white/8 px-4 py-2.5">
          <p className="chat-text whitespace-pre-wrap text-white/90">{content}</p>
          {attachments && attachments.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {attachments.map((att) => (
                <AttachmentChip key={att.file_id} attachment={att} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
