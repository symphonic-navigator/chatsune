/**
 * Navigation tree shape consumed by `OverlayMobileNav`.
 *
 * A `NavLeaf` is a single navigable destination. A `NavSection` is a
 * non-clickable group header whose children render indented underneath.
 * The component walks the array as a single flat list and decides per
 * node whether to render it as a header or a leaf via `isSection`.
 */
export interface NavLeaf {
  id: string
  label: string
  badge?: boolean
}

export interface NavSection {
  id: string
  label: string
  children: NavLeaf[]
}

export type NavNode = NavLeaf | NavSection

export function isSection(node: NavNode): node is NavSection {
  return 'children' in node
}
