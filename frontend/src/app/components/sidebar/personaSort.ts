import type { PersonaDto } from '../../../core/types/persona'

function sortKey(p: PersonaDto): number {
  // None → fall back to created_at so brand-new personas surface at top.
  const stamp = p.last_used_at ?? p.created_at
  return stamp ? Date.parse(stamp) : 0
}

/**
 * Pinned-first, LRU within each group.
 *
 * Sort key per persona is `last_used_at ?? created_at` (descending), so a
 * persona that was just created but never chatted with appears at the top
 * of the unpinned list.
 */
export function sortPersonas(list: PersonaDto[]): PersonaDto[] {
  const pinned: PersonaDto[] = []
  const unpinned: PersonaDto[] = []
  for (const p of list) {
    if (p.pinned) pinned.push(p)
    else unpinned.push(p)
  }
  pinned.sort((a, b) => sortKey(b) - sortKey(a))
  unpinned.sort((a, b) => sortKey(b) - sortKey(a))
  return [...pinned, ...unpinned]
}
