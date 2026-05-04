import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { HistoryItem } from '../HistoryItem'

function makeSession(overrides = {}) {
  return {
    id: 's1',
    persona_id: 'p1',
    title: 'Old title',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  } as any
}

function renderItem(props: Partial<React.ComponentProps<typeof HistoryItem>> = {}) {
  return render(
    <MemoryRouter>
      <HistoryItem
        session={makeSession()}
        isPinned={false}
        isActive={false}
        onClick={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRename={vi.fn()}
        {...props}
      />
    </MemoryRouter>,
  )
}

describe('HistoryItem rename', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows Rename in the overflow menu', () => {
    renderItem()
    fireEvent.click(screen.getByLabelText('More options'))
    expect(screen.getByText('Rename')).toBeInTheDocument()
  })

  it('clicking Rename activates inline edit mode pre-filled with the current title', () => {
    renderItem()
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title') as HTMLInputElement
    expect(input).toHaveFocus()
  })

  it('Enter saves and calls onRename with trimmed value', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: '  New title  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 's1' }), 'New title')
  })

  it('Escape cancels and does not call onRename', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: 'Discarded' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onRename).not.toHaveBeenCalled()
  })

  it('blur saves the current value', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: 'Blurred' } })
    fireEvent.blur(input)
    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 's1' }), 'Blurred')
  })

  it('rejects empty / whitespace-only input', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRename).not.toHaveBeenCalled()
  })

  it('Escape followed by blur does not call onRename', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: 'Changed' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.blur(input)
    expect(onRename).not.toHaveBeenCalled()
  })

  it('Rename menu entry is absent when onRename prop is not provided', () => {
    render(
      <MemoryRouter>
        <HistoryItem
          session={makeSession()}
          isPinned={false}
          isActive={false}
          onClick={vi.fn()}
          onDelete={vi.fn()}
          onTogglePin={vi.fn()}
        />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByLabelText('More options'))
    expect(screen.queryByText('Rename')).not.toBeInTheDocument()
  })
})
