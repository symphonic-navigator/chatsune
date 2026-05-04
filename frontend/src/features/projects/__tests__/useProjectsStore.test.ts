// Tests for the Mindspace projects store. The store registers four
// event-bus subscriptions at module load — those subscriptions are
// re-attached on every dynamic import after ``vi.resetModules()``,
// which the global setup runs in ``beforeEach``. We therefore import
// the store *inside* each test (after mocks are wired) so we know we
// have a fresh module instance with fresh subscriptions.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { ProjectDto } from '../types'

vi.mock('../projectsApi', () => ({
  projectsApi: {
    list: vi.fn(),
  },
}))

function makeProject(overrides: Partial<ProjectDto> = {}): ProjectDto {
  return {
    id: 'p1',
    user_id: 'u1',
    title: 'My Project',
    emoji: null,
    description: null,
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useProjectsStore — load()', () => {
  it('populates the projects map from projectsApi.list', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { projectsApi } = await import('../projectsApi')

    const fixtures = [
      makeProject({ id: 'a', title: 'Alpha' }),
      makeProject({ id: 'b', title: 'Beta' }),
    ]
    vi.mocked(projectsApi.list).mockResolvedValueOnce(fixtures)

    await useProjectsStore.getState().load()

    const state = useProjectsStore.getState()
    expect(state.loaded).toBe(true)
    expect(state.loading).toBe(false)
    expect(Object.keys(state.projects)).toEqual(['a', 'b'])
    expect(state.projects.a.title).toBe('Alpha')
  })

  it('does not start a second load when one is already in flight', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { projectsApi } = await import('../projectsApi')

    let resolve!: (value: ProjectDto[]) => void
    vi.mocked(projectsApi.list).mockReturnValueOnce(
      new Promise<ProjectDto[]>((r) => {
        resolve = r
      }),
    )

    const first = useProjectsStore.getState().load()
    // Second call should bail out early without invoking list again.
    const second = useProjectsStore.getState().load()
    resolve([])
    await first
    await second

    expect(vi.mocked(projectsApi.list)).toHaveBeenCalledTimes(1)
  })
})

describe('useProjectsStore — upsert / remove', () => {
  it('upsert adds a new project', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const project = makeProject({ id: 'x' })
    useProjectsStore.getState().upsert(project)
    expect(useProjectsStore.getState().projects.x).toEqual(project)
  })

  it('upsert replaces an existing project', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'x', title: 'Old' }))
    useProjectsStore.getState().upsert(makeProject({ id: 'x', title: 'New' }))
    expect(useProjectsStore.getState().projects.x.title).toBe('New')
  })

  it('remove deletes a project by id', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'x' }))
    useProjectsStore.getState().remove('x')
    expect(useProjectsStore.getState().projects.x).toBeUndefined()
  })

  it('remove is a no-op for unknown ids', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'x' }))
    const before = useProjectsStore.getState().projects
    useProjectsStore.getState().remove('does-not-exist')
    expect(useProjectsStore.getState().projects).toBe(before)
  })
})

describe('useProjectsStore — event subscriptions', () => {
  it('project.created event upserts the payload', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { eventBus } = await import('../../../core/websocket/eventBus')
    const { Topics } = await import('../../../core/types/events')

    const project = makeProject({ id: 'evt-1', title: 'From Event' })
    eventBus.emit({
      id: 'e1',
      type: Topics.PROJECT_CREATED,
      sequence: '1',
      scope: 'global',
      correlation_id: 'c1',
      timestamp: '2026-05-04T00:00:00Z',
      payload: project as unknown as Record<string, unknown>,
    })

    expect(useProjectsStore.getState().projects['evt-1']).toEqual(project)
  })

  it('project.updated event upserts the payload', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { eventBus } = await import('../../../core/websocket/eventBus')
    const { Topics } = await import('../../../core/types/events')

    useProjectsStore.getState().upsert(makeProject({ id: 'u1', title: 'Old' }))
    const updated = makeProject({ id: 'u1', title: 'Updated' })

    eventBus.emit({
      id: 'e2',
      type: Topics.PROJECT_UPDATED,
      sequence: '1',
      scope: 'global',
      correlation_id: 'c2',
      timestamp: '2026-05-04T00:00:00Z',
      payload: updated as unknown as Record<string, unknown>,
    })

    expect(useProjectsStore.getState().projects.u1.title).toBe('Updated')
  })

  it('project.deleted event removes the project', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { eventBus } = await import('../../../core/websocket/eventBus')
    const { Topics } = await import('../../../core/types/events')

    useProjectsStore.getState().upsert(makeProject({ id: 'd1' }))
    eventBus.emit({
      id: 'e3',
      type: Topics.PROJECT_DELETED,
      sequence: '1',
      scope: 'global',
      correlation_id: 'c3',
      timestamp: '2026-05-04T00:00:00Z',
      payload: { id: 'd1' },
    })

    expect(useProjectsStore.getState().projects.d1).toBeUndefined()
  })

  it('project.pinned.updated event patches only the pinned flag', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { eventBus } = await import('../../../core/websocket/eventBus')
    const { Topics } = await import('../../../core/types/events')

    const original = makeProject({
      id: 'pin1',
      title: 'Keep Title',
      pinned: false,
      knowledge_library_ids: ['lib-1'],
    })
    useProjectsStore.getState().upsert(original)

    eventBus.emit({
      id: 'e4',
      type: Topics.PROJECT_PINNED_UPDATED,
      sequence: '1',
      scope: 'global',
      correlation_id: 'c4',
      timestamp: '2026-05-04T00:00:00Z',
      payload: { id: 'pin1', pinned: true, user_id: 'u1' },
    })

    const after = useProjectsStore.getState().projects.pin1
    expect(after.pinned).toBe(true)
    expect(after.title).toBe('Keep Title')
    expect(after.knowledge_library_ids).toEqual(['lib-1'])
  })

  it('project.pinned.updated is a no-op for unknown project ids', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    const { eventBus } = await import('../../../core/websocket/eventBus')
    const { Topics } = await import('../../../core/types/events')

    eventBus.emit({
      id: 'e5',
      type: Topics.PROJECT_PINNED_UPDATED,
      sequence: '1',
      scope: 'global',
      correlation_id: 'c5',
      timestamp: '2026-05-04T00:00:00Z',
      payload: { id: 'ghost', pinned: true, user_id: 'u1' },
    })

    expect(useProjectsStore.getState().projects.ghost).toBeUndefined()
  })
})
