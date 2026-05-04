import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import AddPersonaCard from '../AddPersonaCard'

describe('AddPersonaCard split', () => {
  it('renders both halves with distinct labels', () => {
    render(<AddPersonaCard onCreateNew={vi.fn()} onImport={vi.fn()} index={0} />)
    expect(screen.getByRole('button', { name: /create new persona/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /import persona from file/i })).toBeInTheDocument()
  })

  it('top half triggers onCreateNew', () => {
    const onCreateNew = vi.fn()
    render(<AddPersonaCard onCreateNew={onCreateNew} onImport={vi.fn()} index={0} />)
    fireEvent.click(screen.getByRole('button', { name: /create new persona/i }))
    expect(onCreateNew).toHaveBeenCalledTimes(1)
  })

  it('bottom half triggers onImport', () => {
    const onImport = vi.fn()
    render(<AddPersonaCard onCreateNew={vi.fn()} onImport={onImport} index={0} />)
    fireEvent.click(screen.getByRole('button', { name: /import persona from file/i }))
    expect(onImport).toHaveBeenCalledTimes(1)
  })
})
