// Recently-used emojis specifically for the project-create / project-edit
// emoji picker. Mirrors the shape of `features/chat/recentEmojisStore.ts`
// but kept separate so the message picker and the project picker can
// each surface their own LRU.
//
// Source of truth lives on the user document (`recent_project_emojis`,
// see `shared/dtos/auth.py`); the store just caches it in-memory:
//
//   - Initial seed: AppLayout pushes `user.recent_project_emojis` here
//     once after authentication completes.
//   - Live updates: AppLayout listens for
//     `Topics.USER_RECENT_PROJECT_EMOJIS_UPDATED` and forwards the
//     emoji list. (No backend endpoint fires that topic yet — Phase 5
//     wires the store only; persistence/event emission is deferred to
//     a later phase per the Mindspace plan.)
//
// LRU bookkeeping (push-to-front, dedupe, max-N) is therefore handled
// server-side once persistence lands; the frontend remains a passive
// view, consistent with the message-emoji store.

import { create } from 'zustand'

interface RecentProjectEmojisState {
  emojis: string[]
  set: (emojis: string[]) => void
}

export const useRecentProjectEmojisStore = create<RecentProjectEmojisState>(
  (set) => ({
    emojis: [],
    set: (emojis) => set({ emojis }),
  }),
)
