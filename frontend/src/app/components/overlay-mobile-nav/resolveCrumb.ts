import { isSection, type NavNode } from './types'

export interface Crumb {
  parent?: string
  leaf: string
}

/**
 * Find `activeId` in `tree` and return its display crumb.
 *
 * - Top-level leaf  → `{ leaf }`.
 * - Child of section → `{ parent: section.label, leaf: child.label }`.
 * - Section id (defensive) → `{ leaf: section.label }`.
 * - Unknown id → `{ leaf: '' }`.
 */
export function resolveCrumb(tree: NavNode[], activeId: string): Crumb {
  for (const node of tree) {
    if (node.id === activeId) {
      return { leaf: node.label }
    }
    if (isSection(node)) {
      const child = node.children.find((c) => c.id === activeId)
      if (child) {
        return { parent: node.label, leaf: child.label }
      }
    }
  }
  return { leaf: '' }
}
