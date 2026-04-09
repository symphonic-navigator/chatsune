import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Sheet } from '../Sheet'

describe('Sheet', () => {
  it('does not render anything when closed', () => {
    render(
      <Sheet isOpen={false} onClose={vi.fn()} ariaLabel="Test sheet">
        <div>content</div>
      </Sheet>,
    )
    expect(screen.queryByText('content')).toBeNull()
  })

  it('renders children and the dialog role when open', () => {
    render(
      <Sheet isOpen={true} onClose={vi.fn()} ariaLabel="Test sheet">
        <div>content</div>
      </Sheet>,
    )
    expect(screen.getByText('content')).toBeTruthy()
    expect(screen.getByRole('dialog', { name: 'Test sheet' })).toBeTruthy()
  })

  it('calls onClose when the backdrop is clicked', () => {
    const onClose = vi.fn()
    render(
      <Sheet isOpen={true} onClose={onClose} ariaLabel="Test sheet">
        <div>content</div>
      </Sheet>,
    )
    // The backdrop is the first element with aria-hidden="true" rendered by
    // the sheet. Querying directly via its role would not work because it
    // has no semantic role.
    const backdrop = document.querySelector('[aria-hidden="true"]') as HTMLElement
    expect(backdrop).toBeTruthy()
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when Escape is pressed', () => {
    const onClose = vi.fn()
    render(
      <Sheet isOpen={true} onClose={onClose} ariaLabel="Test sheet">
        <div>content</div>
      </Sheet>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
