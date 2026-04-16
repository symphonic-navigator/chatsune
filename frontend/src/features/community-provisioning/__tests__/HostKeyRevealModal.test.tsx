import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HostKeyRevealModal } from '../HostKeyRevealModal'

describe('HostKeyRevealModal', () => {
  it('renders the plaintext and the one-shot warning', () => {
    render(<HostKeyRevealModal plaintext="sk_test_ABC123" onClose={() => {}} />)
    expect(screen.getByText('sk_test_ABC123')).toBeInTheDocument()
    expect(screen.getByText(/shown once/i)).toBeInTheDocument()
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument()
  })

  it("dismissal requires clicking 'I've saved it'", async () => {
    const onClose = vi.fn()
    render(<HostKeyRevealModal plaintext="sk_test_ABC123" onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /i've saved it/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
