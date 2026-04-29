import { render, screen, fireEvent } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { OverlayMobileNav } from './OverlayMobileNav'
import type { NavNode } from './types'

// scrollIntoView is not implemented by jsdom; stub once for the file.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

const flatTree: NavNode[] = [
  { id: 'users', label: 'Users' },
  { id: 'system', label: 'System' },
]

const hierarchicalTree: NavNode[] = [
  { id: 'about-me', label: 'About me' },
  {
    id: 'settings',
    label: 'Settings',
    children: [
      { id: 'llm-providers', label: 'LLM Providers' },
      { id: 'voice', label: 'Voice' },
    ],
  },
]

describe('OverlayMobileNav — trigger rendering', () => {
  it('renders the leaf only for a flat tree', () => {
    render(
      <OverlayMobileNav
        tree={flatTree}
        activeId="system"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger.textContent).toContain('System')
    expect(trigger.textContent).not.toContain('–')
  })

  it('renders parent – leaf for a section child', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button')
    // Real En-Dash, U+2013, never a hyphen.
    expect(trigger.textContent).toContain('Settings–Voice')
  })

  it('renders leaf only for a leaf-only top tab', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button')
    expect(trigger.textContent).toContain('About me')
    expect(trigger.textContent).not.toContain('–')
  })
})

describe('OverlayMobileNav — panel behaviour', () => {
  it('toggles aria-expanded on trigger click', () => {
    render(
      <OverlayMobileNav
        tree={flatTree}
        activeId="users"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders sections as presentation and leaves as options when open', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    // Leaf-only top renders as option
    expect(screen.getByRole('option', { name: 'About me' })).toBeInTheDocument()
    // Section header renders as presentation (not as option)
    expect(screen.queryByRole('option', { name: 'Settings' })).toBeNull()
    // Children of the section render as options
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Voice' })).toBeInTheDocument()
    // Active leaf is aria-selected
    expect(screen.getByRole('option', { name: 'Voice' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  it('calls onSelect and closes panel when a leaf is clicked', () => {
    const onSelect = vi.fn()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={onSelect}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('option', { name: 'LLM Providers' }))
    expect(onSelect).toHaveBeenCalledWith('llm-providers')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('does nothing when a section header is clicked', () => {
    const onSelect = vi.fn()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={onSelect}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    // Find the section header by its visible text — it has no role=option.
    fireEvent.click(screen.getByText('Settings'))
    expect(onSelect).not.toHaveBeenCalled()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})
