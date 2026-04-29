/**
 * Static navigation tree for the UserModal 2-level pill navigation.
 * Provides type definitions, the tree itself, and resolver helpers.
 */

import type { NavLeaf, NavNode, NavSection } from '../overlay-mobile-nav/types'

export type TopTabId =
  | 'about-me'
  | 'personas'
  | 'chats'
  | 'knowledge'
  | 'my-data'
  | 'settings'
  | 'job-log'

export type SubTabId =
  // chats
  // 'projects' is intentionally retained in the type union so legacy persisted
  // sub-tab IDs (e.g. in localStorage) still type-check during resolution.
  // The Projects entry is hidden from the tree below — see FOR_LATER.md.
  | 'projects'
  | 'history'
  | 'bookmarks'
  // my-data
  | 'uploads'
  | 'artefacts'
  | 'images'
  // settings
  | 'llm-providers'
  | 'community-provisioning'
  | 'models'
  | 'mcp'
  | 'integrations'
  | 'display'
  | 'voice'

/** Any navigable leaf — either a standalone top tab or a sub-tab. */
export type LeafId = TopTabId | SubTabId

interface SubTab { id: SubTabId; label: string }
export interface TopTab { id: TopTabId; label: string; children?: SubTab[] }

export const TABS_TREE: TopTab[] = [
  { id: 'about-me',  label: 'About me' },
  { id: 'personas',  label: 'Personas' },
  {
    id: 'chats',
    label: 'Chats',
    children: [
      // Projects sub-tab hidden — feature not yet ready (see FOR_LATER.md).
      { id: 'history',   label: 'History' },
      { id: 'bookmarks', label: 'Bookmarks' },
    ],
  },
  { id: 'knowledge', label: 'Knowledge' },
  {
    id: 'my-data',
    label: 'My data',
    children: [
      { id: 'uploads',   label: 'Uploads' },
      { id: 'artefacts', label: 'Artefacts' },
      { id: 'images',    label: 'Images' },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    children: [
      { id: 'llm-providers',          label: 'LLM Providers' },
      { id: 'community-provisioning', label: 'Community Provisioning' },
      { id: 'models',                 label: 'Models' },
      { id: 'mcp',                    label: 'MCP' },
      { id: 'integrations',           label: 'Integrations' },
      { id: 'display',                label: 'Display' },
      { id: 'voice',                  label: 'Voice' },
    ],
  },
  { id: 'job-log', label: 'Job-Log' },
]

// Build a lookup map: sub-tab id → parent top-tab id
const _subToTop = new Map<SubTabId, TopTabId>()
for (const top of TABS_TREE) {
  if (top.children) {
    for (const sub of top.children) {
      _subToTop.set(sub.id, top.id)
    }
  }
}

// All known top-tab IDs as a set for fast checking
const _topIds = new Set<string>(TABS_TREE.map((t) => t.id))

/**
 * Resolve any leaf ID (top or sub) to a `{ top, sub? }` pair.
 * Handles legacy IDs that were renamed:
 *   - `'llm'`      → `{ top: 'settings', sub: 'llm-providers' }`
 *   - `'settings'` → `{ top: 'settings', sub: 'display' }`  (old flat Settings tab)
 */
export function resolveLeaf(leaf: LeafId | string): { top: TopTabId; sub?: SubTabId } {
  // Legacy renames
  if (leaf === 'llm') return { top: 'settings', sub: 'llm-providers' }
  // Old flat 'settings' tab → now Display under Settings
  // But 'settings' is now also a valid TopTabId — if passed as a leaf we open
  // Settings with its first sub selected (resolveLeaf returns top only; the
  // caller then picks the remembered or first sub).  No rename needed here
  // because 'settings' IS a valid TopTabId.

  if (_topIds.has(leaf)) {
    return { top: leaf as TopTabId }
  }

  const parent = _subToTop.get(leaf as SubTabId)
  if (parent) {
    return { top: parent, sub: leaf as SubTabId }
  }

  // Unknown leaf — fall back to about-me
  return { top: 'about-me' }
}

/** Return the first sub-tab id for a top tab, or undefined for leaf-only tops. */
export function firstSubOf(topId: TopTabId): SubTabId | undefined {
  const top = TABS_TREE.find((t) => t.id === topId)
  return top?.children?.[0]?.id
}

/**
 * Convert `TABS_TREE` to the shape `OverlayMobileNav` consumes.
 *
 * `badges` is keyed by leaf id; pass `true` to flag a leaf so the mobile
 * nav renders the leaf and its containing section header with the
 * red-`!` indicator.
 */
export function toMobileNavTree(
  badges: Record<string, boolean> = {},
): NavNode[] {
  return TABS_TREE.map((top): NavNode => {
    if (top.children) {
      const section: NavSection = {
        id: top.id,
        label: top.label,
        children: top.children.map(
          (sub): NavLeaf => ({
            id: sub.id,
            label: sub.label,
            badge: badges[sub.id] || undefined,
          }),
        ),
      }
      return section
    }
    const leaf: NavLeaf = {
      id: top.id,
      label: top.label,
      badge: badges[top.id] || undefined,
    }
    return leaf
  })
}
