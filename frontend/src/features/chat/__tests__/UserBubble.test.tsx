import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AttachmentRefDto } from '../../../core/api/chat'
import { UserBubble } from '../UserBubble'

// Spy on AttachmentChip renders so the memoisation tests can observe whether
// UserBubble re-entered its render body on a given update.
const attachmentChipRenderSpy = vi.fn()

vi.mock('../AttachmentChip', () => ({
  AttachmentChip: ({ attachment }: { attachment: AttachmentRefDto }) => {
    attachmentChipRenderSpy()
    return <div data-testid="attachment-chip">{attachment.file_id}</div>
  },
}))

describe('UserBubble', () => {
  const baseProps = { content: 'Hello, assistant!', onEdit: vi.fn(), isEditable: true }

  it('renders user message content', () => {
    render(<UserBubble {...baseProps} />)
    expect(screen.getByText('Hello, assistant!')).toBeInTheDocument()
  })

  it('shows edit button on hover', () => {
    render(<UserBubble {...baseProps} />)
    fireEvent.mouseEnter(screen.getByTestId('user-bubble'))
    expect(screen.getByTestId('edit-button')).toBeInTheDocument()
  })

  it('enters edit mode on edit click', () => {
    render(<UserBubble {...baseProps} />)
    fireEvent.mouseEnter(screen.getByTestId('user-bubble'))
    fireEvent.click(screen.getByTestId('edit-button'))
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Hello, assistant!')
  })

  it('calls onEdit with new content on submit', async () => {
    const onEdit = vi.fn()
    render(<UserBubble {...baseProps} onEdit={onEdit} />)
    fireEvent.mouseEnter(screen.getByTestId('user-bubble'))
    fireEvent.click(screen.getByTestId('edit-button'))
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement
    await userEvent.clear(textarea)
    await userEvent.type(textarea, 'Updated message')
    fireEvent.click(screen.getByTestId('edit-submit'))
    expect(onEdit).toHaveBeenCalledWith('Updated message')
  })

  it('exits edit mode on cancel', () => {
    render(<UserBubble {...baseProps} />)
    fireEvent.mouseEnter(screen.getByTestId('user-bubble'))
    fireEvent.click(screen.getByTestId('edit-button'))
    fireEvent.click(screen.getByTestId('edit-cancel'))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.getByText('Hello, assistant!')).toBeInTheDocument()
  })

  it('does not show edit button when not editable', () => {
    render(<UserBubble {...baseProps} isEditable={false} />)
    fireEvent.mouseEnter(screen.getByTestId('user-bubble'))
    expect(screen.queryByTestId('edit-button')).not.toBeInTheDocument()
  })
})

describe('UserBubble — memoisation', () => {
  const attachment: AttachmentRefDto = {
    file_id: 'att-1',
    display_name: 'file.png',
    media_type: 'image/png',
    size_bytes: 100,
    thumbnail_b64: null,
    text_preview: null,
  }

  it('re-renders when content changes', () => {
    const onEdit = vi.fn()
    const onBookmark = vi.fn()
    const stableAttachments = [attachment]
    attachmentChipRenderSpy.mockClear()
    const { rerender } = render(
      <UserBubble
        content="first"
        attachments={stableAttachments}
        onEdit={onEdit}
        onBookmark={onBookmark}
        isEditable
      />
    )
    const before = attachmentChipRenderSpy.mock.calls.length
    rerender(
      <UserBubble
        content="second"
        attachments={stableAttachments}
        onEdit={onEdit}
        onBookmark={onBookmark}
        isEditable
      />
    )
    expect(attachmentChipRenderSpy.mock.calls.length).toBeGreaterThan(before)
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('does NOT re-render when only the onEdit / onBookmark callback identity changes', () => {
    attachmentChipRenderSpy.mockClear()
    // Stable references — attachments array identity must not change, otherwise
    // the memo equality (which compares by reference) will correctly rerender.
    const stableAttachments = [attachment]
    const { rerender } = render(
      <UserBubble
        content="stable content"
        attachments={stableAttachments}
        onEdit={vi.fn()}
        onBookmark={vi.fn()}
        isEditable
      />
    )
    const before = attachmentChipRenderSpy.mock.calls.length
    rerender(
      <UserBubble
        content="stable content"
        attachments={stableAttachments}
        onEdit={vi.fn()}
        onBookmark={vi.fn()}
        isEditable
      />
    )
    expect(attachmentChipRenderSpy.mock.calls.length).toBe(before)
  })
})
