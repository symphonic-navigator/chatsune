import { describe, expect, it } from 'vitest'
import { toMobileNavTree } from './userModalTree'

describe('toMobileNavTree', () => {
  it('converts TABS_TREE to NavNode[] preserving order, leaves and sections', () => {
    const nodes = toMobileNavTree()
    // The first entry is About me — a leaf-only top tab.
    expect(nodes[0]).toEqual({ id: 'about-me', label: 'About me' })
    // Settings is a section with children.
    const settings = nodes.find((n) => n.id === 'settings')
    expect(settings).toBeTruthy()
    expect('children' in settings!).toBe(true)
    if ('children' in settings!) {
      expect(settings.children[0]).toEqual({ id: 'llm-providers', label: 'LLM Providers' })
    }
  })

  it('applies badges by leaf id', () => {
    const nodes = toMobileNavTree({ 'llm-providers': true })
    const settings = nodes.find((n) => n.id === 'settings')!
    if (!('children' in settings)) throw new Error('expected section')
    const llm = settings.children.find((c) => c.id === 'llm-providers')!
    expect(llm.badge).toBe(true)
    // Other leaves are not badged.
    const voice = settings.children.find((c) => c.id === 'voice')!
    expect(voice.badge).toBeUndefined()
  })
})
