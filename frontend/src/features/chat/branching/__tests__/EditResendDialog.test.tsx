import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { EditResendDialog } from '../EditResendDialog'

describe('EditResendDialog (case 1)', () => {
  function renderDialog(overrides: Partial<React.ComponentProps<typeof EditResendDialog>> = {}) {
    const props: React.ComponentProps<typeof EditResendDialog> = {
      isOpen: true,
      onReplace: vi.fn(),
      onBranch: vi.fn(),
      onClose: vi.fn(),
      ...overrides,
    }
    return { ...render(<EditResendDialog {...props} />), props }
  }

  it('renders the title with both options', () => {
    renderDialog()
    expect(
      screen.getByText('Replace response or new branch?'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('edit-resend-replace')).toBeInTheDocument()
    expect(screen.getByTestId('edit-resend-branch')).toBeInTheDocument()
  })

  it('"Replace response" calls onReplace and not onBranch', () => {
    const onReplace = vi.fn()
    const onBranch = vi.fn()
    renderDialog({ onReplace, onBranch })
    fireEvent.click(screen.getByTestId('edit-resend-replace'))
    expect(onReplace).toHaveBeenCalled()
    expect(onBranch).not.toHaveBeenCalled()
  })

  it('"New branch" calls onBranch and not onReplace', () => {
    const onReplace = vi.fn()
    const onBranch = vi.fn()
    renderDialog({ onReplace, onBranch })
    fireEvent.click(screen.getByTestId('edit-resend-branch'))
    expect(onBranch).toHaveBeenCalled()
    expect(onReplace).not.toHaveBeenCalled()
  })

  it('cancel calls onClose only', () => {
    const onClose = vi.fn()
    const onReplace = vi.fn()
    const onBranch = vi.fn()
    renderDialog({ onClose, onReplace, onBranch })
    fireEvent.click(screen.getByTestId('edit-resend-cancel'))
    expect(onClose).toHaveBeenCalled()
    expect(onReplace).not.toHaveBeenCalled()
    expect(onBranch).not.toHaveBeenCalled()
  })

  it('returns null when isOpen is false', () => {
    renderDialog({ isOpen: false })
    expect(screen.queryByTestId('edit-resend-dialog')).not.toBeInTheDocument()
  })
})

// The "case 2 goes directly to name dialog" path lives in the integration
// flow (no dialog is opened — ChatView calls setBranchDialogContext directly).
// That branch is covered by ``branchFlow.integration.test.tsx`` and the
// MessageList action-bar tests, so we deliberately don't reproduce it here.
