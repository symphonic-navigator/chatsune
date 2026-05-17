import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import {
  BranchNameDialog,
  computeDefaultBranchName,
} from '../BranchNameDialog'

describe('computeDefaultBranchName', () => {
  it('returns "(Variante 1)" when no siblings match the prefix', () => {
    const name = computeDefaultBranchName('Chris fragt nach Quantenphysik', [
      { title: 'Andere Unterhaltung' },
      { title: null },
    ])
    expect(name).toBe('Chris fragt nach Quantenphysik (Variante 1)')
  })

  it('returns max-sibling + 1 when matching variants exist', () => {
    const name = computeDefaultBranchName('Parent', [
      { title: 'Parent (Variante 1)' },
      { title: 'Parent (Variante 3)' },
      { title: 'Parent (Variante 2)' },
      { title: 'Unrelated' },
    ])
    expect(name).toBe('Parent (Variante 4)')
  })

  it('ignores malformed variant suffixes', () => {
    const name = computeDefaultBranchName('Parent', [
      { title: 'Parent (Variante abc)' },
      { title: 'Parent (Variante 2)' },
    ])
    expect(name).toBe('Parent (Variante 3)')
  })
})

describe('BranchNameDialog', () => {
  function renderDialog(overrides: Partial<React.ComponentProps<typeof BranchNameDialog>> = {}) {
    const props: React.ComponentProps<typeof BranchNameDialog> = {
      isOpen: true,
      parentTitle: 'Parent Title',
      allSessions: [],
      onConfirm: vi.fn(),
      onClose: vi.fn(),
      ...overrides,
    }
    return { ...render(<BranchNameDialog {...props} />), props }
  }

  it('renders the German title and pre-fills the default name', () => {
    renderDialog()
    expect(screen.getByText('Neuen Branch erstellen')).toBeInTheDocument()
    const input = screen.getByTestId('branch-name-input') as HTMLInputElement
    expect(input.value).toBe('Parent Title (Variante 1)')
  })

  it('seeds the next variant index from siblings', () => {
    renderDialog({
      allSessions: [
        { title: 'Parent Title (Variante 2)' },
        { title: 'Parent Title (Variante 5)' },
      ],
    })
    const input = screen.getByTestId('branch-name-input') as HTMLInputElement
    expect(input.value).toBe('Parent Title (Variante 6)')
  })

  it('accepts an edited name and calls onConfirm with the trimmed value', async () => {
    const onConfirm = vi.fn()
    renderDialog({ onConfirm })
    const input = screen.getByTestId('branch-name-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '  Mein Branch  ' } })
    fireEvent.click(screen.getByTestId('branch-name-confirm'))
    expect(onConfirm).toHaveBeenCalledWith('Mein Branch')
  })

  it('cancel does not call onConfirm', () => {
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    renderDialog({ onConfirm, onClose })
    fireEvent.click(screen.getByTestId('branch-name-cancel'))
    expect(onConfirm).not.toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('disables the confirm button when the input is empty after trim', () => {
    renderDialog()
    const input = screen.getByTestId('branch-name-input') as HTMLInputElement
    fireEvent.change(input, { target: { value: '   ' } })
    const confirm = screen.getByTestId('branch-name-confirm') as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
  })

  it('shows a loader and dismisses the input while submitting', async () => {
    // ``onConfirm`` returns an unresolved promise so the dialog stays in
    // its submitting state long enough for us to assert on the loader.
    const resolveFn: { current: (() => void) | null } = { current: null }
    const onConfirm = vi.fn(
      () => new Promise<void>((res) => { resolveFn.current = res }),
    )
    renderDialog({ onConfirm })
    fireEvent.click(screen.getByTestId('branch-name-confirm'))
    expect(screen.getByTestId('branch-name-dialog-loader')).toBeInTheDocument()
    expect(screen.queryByTestId('branch-name-input')).not.toBeInTheDocument()
    // Resolve to clean up the open promise so vitest doesn't hold open handles.
    resolveFn.current?.()
  })

  it('returns null when isOpen is false', () => {
    renderDialog({ isOpen: false })
    expect(screen.queryByTestId('branch-name-dialog')).not.toBeInTheDocument()
  })
})
