import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatInput } from '../ChatInput'

describe('ChatInput', () => {
  it('renders textarea', () => {
    render(<ChatInput onSend={vi.fn()} onCancel={vi.fn()} onFilesSelected={vi.fn()} onToggleBrowser={vi.fn()} hasPendingUploads={false} isStreaming={false} disabled={false} />)
    expect(screen.getByPlaceholderText('Type a message...')).toBeInTheDocument()
  })

  it('calls onSend with trimmed text on submit', async () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} onCancel={vi.fn()} onFilesSelected={vi.fn()} onToggleBrowser={vi.fn()} hasPendingUploads={false} isStreaming={false} disabled={false} />)
    const textarea = screen.getByPlaceholderText('Type a message...')
    await userEvent.type(textarea, 'Hello world')
    fireEvent.click(screen.getByTestId('send-button'))
    expect(onSend).toHaveBeenCalledWith('Hello world')
  })

  it('does not submit empty text', () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} onCancel={vi.fn()} onFilesSelected={vi.fn()} onToggleBrowser={vi.fn()} hasPendingUploads={false} isStreaming={false} disabled={false} />)
    fireEvent.click(screen.getByTestId('send-button'))
    expect(onSend).not.toHaveBeenCalled()
  })

  it('shows cancel button while streaming', () => {
    render(<ChatInput onSend={vi.fn()} onCancel={vi.fn()} onFilesSelected={vi.fn()} onToggleBrowser={vi.fn()} hasPendingUploads={false} isStreaming={true} disabled={false} />)
    expect(screen.getByTestId('cancel-button')).toBeInTheDocument()
  })

  it('calls onCancel when cancel button clicked', () => {
    const onCancel = vi.fn()
    render(<ChatInput onSend={vi.fn()} onCancel={onCancel} onFilesSelected={vi.fn()} onToggleBrowser={vi.fn()} hasPendingUploads={false} isStreaming={true} disabled={false} />)
    fireEvent.click(screen.getByTestId('cancel-button'))
    expect(onCancel).toHaveBeenCalled()
  })

  it('clears textarea after send', async () => {
    const onSend = vi.fn()
    render(<ChatInput onSend={onSend} onCancel={vi.fn()} onFilesSelected={vi.fn()} onToggleBrowser={vi.fn()} hasPendingUploads={false} isStreaming={false} disabled={false} />)
    const textarea = screen.getByPlaceholderText('Type a message...') as HTMLTextAreaElement
    await userEvent.type(textarea, 'Hello')
    fireEvent.click(screen.getByTestId('send-button'))
    expect(textarea.value).toBe('')
  })
})
