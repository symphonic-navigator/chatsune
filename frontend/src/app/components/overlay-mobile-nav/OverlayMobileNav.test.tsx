import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

  it('closes the panel on Escape', () => {
    render(
      <OverlayMobileNav
        tree={flatTree}
        activeId="users"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes the panel on backdrop click', () => {
    render(
      <OverlayMobileNav
        tree={flatTree}
        activeId="users"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    const backdrop = screen.getByTestId('overlay-mobile-nav-backdrop')
    fireEvent.click(backdrop)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('does not close on click inside the listbox', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    // Click on a non-clickable section header — panel must stay open.
    fireEvent.click(screen.getByText('Settings'))
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})

const treeWithBadge: NavNode[] = [
  { id: 'about-me', label: 'About me' },
  {
    id: 'settings',
    label: 'Settings',
    children: [
      { id: 'llm-providers', label: 'LLM Providers', badge: true },
      { id: 'voice', label: 'Voice' },
    ],
  },
]

describe('OverlayMobileNav — badge propagation', () => {
  it('renders a badge on the flagged leaf', () => {
    render(
      <OverlayMobileNav
        tree={treeWithBadge}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    const llm = screen.getByRole('option', { name: /LLM Providers/i })
    expect(llm.querySelector('[data-testid="leaf-badge"]')).toBeTruthy()
  })

  it('renders a badge on the section header containing a flagged leaf', () => {
    render(
      <OverlayMobileNav
        tree={treeWithBadge}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    // Only Settings has a flagged child in this tree, so exactly one
    // section-badge should render.
    expect(screen.queryAllByTestId('section-badge')).toHaveLength(1)
  })

  it('does not render a section badge if no child is flagged', () => {
    const tree: NavNode[] = [
      {
        id: 'chats',
        label: 'Chats',
        children: [{ id: 'history', label: 'History' }],
      },
    ]
    render(
      <OverlayMobileNav tree={tree} activeId="history" onSelect={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.queryByTestId('section-badge')).toBeNull()
  })
})

describe('OverlayMobileNav — accent colour', () => {
  it('applies the override colour to the open trigger border and active row', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
        accentColour="#ff00aa"
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    // Trigger picks up the accent on its inline border-color when open.
    // jsdom normalises hex to rgb(), so match either form.
    expect(trigger.style.borderColor).toMatch(/#ff00aa|rgb\(255,\s*0,\s*170\)/i)
    // Active leaf picks up the accent on its inline color + background.
    const active = screen.getByRole('option', { name: 'Voice' })
    expect(active.style.color).toMatch(/#ff00aa|rgb\(255,\s*0,\s*170\)/i)
    expect(active.style.backgroundColor).not.toBe('')
  })
})

describe('OverlayMobileNav — keyboard and focus', () => {
  it('focuses the active option and scrolls it into view on open', () => {
    const scrollSpy = vi.spyOn(Element.prototype, 'scrollIntoView')
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.getByRole('option', { name: 'Voice' })).toHaveFocus()
    expect(scrollSpy).toHaveBeenCalled()
    scrollSpy.mockRestore()
  })

  it('moves focus through clickable leaves with ArrowDown / ArrowUp', async () => {
    const user = userEvent.setup()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.getByRole('option', { name: 'About me' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: 'Voice' })).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toHaveFocus()
  })

  it('selects the focused leaf on Enter', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={onSelect}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onSelect).toHaveBeenCalledWith('llm-providers')
  })
})
