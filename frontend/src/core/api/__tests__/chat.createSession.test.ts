// Mindspace Phase 10 / Task 40 — chatApi.createSession forwards
// ``project_id`` for the neutral-trigger flow.
//
// The persona overlay, sidebar pin and PersonasTab all redirect to
// ``/chat/{personaId}?new=1``; ``ChatView`` then calls
// ``chatApi.createSession`` with the persona's ``default_project_id``
// (``null`` when unset). The endpoint accepts the new field but it
// must NOT appear in the body when the caller passes nothing — older
// backend builds reject unknown body keys, and we want the wire to
// stay quiet for the common path.

import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../client', async () => {
  const actual = await vi.importActual<object>('../client')
  return {
    ...actual,
    api: {
      post: vi.fn(),
      get: vi.fn(),
      patch: vi.fn(),
      put: vi.fn(),
      delete: vi.fn(),
    },
  }
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('chatApi.createSession', () => {
  it('omits project_id when no second arg is supplied', async () => {
    const { api } = await import('../client')
    const { chatApi } = await import('../chat')

    vi.mocked(api.post).mockResolvedValueOnce({})
    await chatApi.createSession('persona-1')

    expect(vi.mocked(api.post)).toHaveBeenCalledWith('/api/chat/sessions', {
      persona_id: 'persona-1',
    })
  })

  it('forwards project_id when provided', async () => {
    const { api } = await import('../client')
    const { chatApi } = await import('../chat')

    vi.mocked(api.post).mockResolvedValueOnce({})
    await chatApi.createSession('persona-1', 'proj-trek')

    expect(vi.mocked(api.post)).toHaveBeenCalledWith('/api/chat/sessions', {
      persona_id: 'persona-1',
      project_id: 'proj-trek',
    })
  })

  it('forwards project_id=null explicitly when caller passes null', async () => {
    const { api } = await import('../client')
    const { chatApi } = await import('../chat')

    vi.mocked(api.post).mockResolvedValueOnce({})
    await chatApi.createSession('persona-1', null)

    expect(vi.mocked(api.post)).toHaveBeenCalledWith('/api/chat/sessions', {
      persona_id: 'persona-1',
      project_id: null,
    })
  })
})
