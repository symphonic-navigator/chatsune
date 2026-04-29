import { render, screen } from '@testing-library/react'
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
    const trigger = screen.getByRole('button', { name: /system/i })
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
