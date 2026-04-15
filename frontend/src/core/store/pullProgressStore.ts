import { create } from "zustand"
import type { BaseEvent } from "../types/events"
import type { PullHandleDto } from "../api/ollamaLocal"

export interface PullEntry {
  pullId: string
  slug: string
  status: string
  completed: number | null
  total: number | null
  startedAt: string
}

interface StartedPayload {
  pull_id: string
  scope: string
  slug: string
  timestamp: string
}

interface ProgressPayload {
  pull_id: string
  scope: string
  status: string
  digest: string | null
  completed: number | null
  total: number | null
  timestamp: string
}

interface TerminalPayload {
  pull_id: string
  scope: string
  slug: string
  timestamp: string
}

interface PullProgressState {
  byScope: Record<string, Record<string, PullEntry>>
  handleEvent: (event: BaseEvent) => void
  hydrateFromList: (scope: string, pulls: PullHandleDto[]) => void
}

function upsert(
  byScope: Record<string, Record<string, PullEntry>>,
  scope: string,
  pullId: string,
  patch: Partial<PullEntry> & { pullId: string },
): Record<string, Record<string, PullEntry>> {
  const existing = byScope[scope]?.[pullId]
  const entry: PullEntry = existing
    ? { ...existing, ...patch }
    : {
        pullId,
        slug: patch.slug ?? "",
        status: patch.status ?? "",
        completed: patch.completed ?? null,
        total: patch.total ?? null,
        startedAt: patch.startedAt ?? new Date().toISOString(),
      }
  return {
    ...byScope,
    [scope]: { ...(byScope[scope] ?? {}), [pullId]: entry },
  }
}

function remove(
  byScope: Record<string, Record<string, PullEntry>>,
  scope: string,
  pullId: string,
): Record<string, Record<string, PullEntry>> {
  const scoped = { ...(byScope[scope] ?? {}) }
  delete scoped[pullId]
  return { ...byScope, [scope]: scoped }
}

export const usePullProgressStore = create<PullProgressState>((set, get) => ({
  byScope: {},

  handleEvent: (event) => {
    switch (event.type) {
      case "llm.model.pull.started": {
        const p = event.payload as unknown as StartedPayload
        set({
          byScope: upsert(get().byScope, p.scope, p.pull_id, {
            pullId: p.pull_id,
            slug: p.slug,
            status: "",
            completed: null,
            total: null,
            startedAt: p.timestamp,
          }),
        })
        return
      }
      case "llm.model.pull.progress": {
        const p = event.payload as unknown as ProgressPayload
        if (!get().byScope[p.scope]?.[p.pull_id]) return
        set({
          byScope: upsert(get().byScope, p.scope, p.pull_id, {
            pullId: p.pull_id,
            status: p.status,
            completed: p.completed,
            total: p.total,
          }),
        })
        return
      }
      case "llm.model.pull.completed":
      case "llm.model.pull.cancelled":
      case "llm.model.pull.failed": {
        const p = event.payload as unknown as TerminalPayload
        set({ byScope: remove(get().byScope, p.scope, p.pull_id) })
        return
      }
      default:
        return
    }
  },

  hydrateFromList: (scope, pulls) => {
    set({
      byScope: {
        ...get().byScope,
        [scope]: Object.fromEntries(
          pulls.map((p) => [
            p.pull_id,
            {
              pullId: p.pull_id,
              slug: p.slug,
              status: p.status,
              completed: null,
              total: null,
              startedAt: p.started_at,
            },
          ]),
        ),
      },
    })
  },
}))
