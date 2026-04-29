import { describe, expect, it } from 'vitest'
import { resolveCrumb } from './resolveCrumb'
import type { NavNode } from './types'

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
  { id: 'job-log', label: 'Job-Log' },
]

describe('resolveCrumb', () => {
  it('returns leaf only for flat-tree active id', () => {
    expect(resolveCrumb(flatTree, 'users')).toEqual({ leaf: 'Users' })
  })

  it('returns parent + leaf for a section child', () => {
    expect(resolveCrumb(hierarchicalTree, 'voice')).toEqual({
      parent: 'Settings',
      leaf: 'Voice',
    })
  })

  it('returns leaf only for a leaf-only top tab in a hierarchical tree', () => {
    expect(resolveCrumb(hierarchicalTree, 'about-me')).toEqual({
      leaf: 'About me',
    })
  })

  it('returns leaf only when active id matches a section (defensive)', () => {
    expect(resolveCrumb(hierarchicalTree, 'settings')).toEqual({
      leaf: 'Settings',
    })
  })

  it('falls back to an empty leaf when active id is unknown', () => {
    expect(resolveCrumb(flatTree, 'does-not-exist')).toEqual({ leaf: '' })
  })
})
