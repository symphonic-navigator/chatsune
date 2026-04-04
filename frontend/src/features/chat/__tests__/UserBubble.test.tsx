import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UserBubble } from '../UserBubble'

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
