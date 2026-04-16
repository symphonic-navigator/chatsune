import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiKeyRevealModal } from '../ApiKeyRevealModal'

describe('ApiKeyRevealModal', () => {
  it('renders the plaintext and the one-shot warning', () => {
    render(<ApiKeyRevealModal plaintext="ck_user_abc_DEF456" onClose={() => {}} />)
    expect(screen.getByText('ck_user_abc_DEF456')).toBeInTheDocument()
    expect(screen.getByText(/shown once/i)).toBeInTheDocument()
    expect(screen.getByText(/not be shown again/i)).toBeInTheDocument()
  })

  it('calls onClose when Done is clicked', async () => {
    const onClose = vi.fn()
    render(<ApiKeyRevealModal plaintext="ck_user_abc_DEF456" onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /done/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
