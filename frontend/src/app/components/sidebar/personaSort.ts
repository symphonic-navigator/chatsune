import type { PersonaDto } from '../../../core/types/persona'

/**
 * Stable pinned-first partition. Preserves the incoming list order, which is
 * authoritative: the API returns personas already sorted by display_order, and
 * optimistic reorder mutates array order (not display_order fields). Sorting
 * by display_order would fight optimistic updates.
 */
export function sortPersonas(list: PersonaDto[]): PersonaDto[] {
  const pinned: PersonaDto[] = []
  const unpinned: PersonaDto[] = []
  for (const p of list) {
    if (p.pinned) pinned.push(p)
    else unpinned.push(p)
  }
  return [...pinned, ...unpinned]
}
