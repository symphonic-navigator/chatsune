import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MobileSidebarHeader } from './MobileSidebarHeader'

describe('MobileSidebarHeader — main view', () => {
  it('renders the logo + Chatsune label', () => {
    render(<MobileSidebarHeader onClose={() => {}} />)
    expect(screen.getByText('Chatsune')).toBeInTheDocument()
  })

  it('calls onClose when the logo area is clicked', async () => {
    const onClose = vi.fn()
    render(<MobileSidebarHeader onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close sidebar/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when the ✕ button is clicked', async () => {
    const onClose = vi.fn()
    render(<MobileSidebarHeader onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close drawer/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

describe('MobileSidebarHeader — overlay mode', () => {
  it('renders title and back arrow when title is provided', () => {
    render(<MobileSidebarHeader title="New Chat" onBack={() => {}} onClose={() => {}} />)
    expect(screen.getByText('New Chat')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /back to main/i })).toBeInTheDocument()
  })

  it('calls onBack — not onClose — when the back area is clicked', async () => {
    const onBack = vi.fn()
    const onClose = vi.fn()
    render(<MobileSidebarHeader title="History" onBack={onBack} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /back to main/i }))
    expect(onBack).toHaveBeenCalledOnce()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose when the ✕ button is clicked', async () => {
    const onBack = vi.fn()
    const onClose = vi.fn()
    render(<MobileSidebarHeader title="History" onBack={onBack} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close drawer/i }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(onBack).not.toHaveBeenCalled()
  })
})
