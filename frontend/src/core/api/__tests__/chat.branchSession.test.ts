// Branching — ``chatApi.branchSession`` request shape.
//
// The endpoint contract (spec ``devdocs/specs/2026-05-17-branching-design.md``
// §5.1) requires:
//   POST /api/chat/sessions/{parent_session_id}/branch
//   Body: { fork_message_id: str | null, name: str }
//
// Both halves matter: the path must carry the PARENT session id, not the
// fork-point id, and the body must use snake_case keys to match the
// backend Pydantic model. This test pins both.

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

describe('chatApi.branchSession', () => {
  it('POSTs to /api/chat/sessions/<parent>/branch with the snake_case body', async () => {
    const { api } = await import('../client')
    const { chatApi } = await import('../chat')

    vi.mocked(api.post).mockResolvedValueOnce({ id: 'branch-1' })
    await chatApi.branchSession('parent-1', 'assistant-7', 'My Branch')

    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      '/api/chat/sessions/parent-1/branch',
      { fork_message_id: 'assistant-7', name: 'My Branch' },
    )
  })

  it('sends fork_message_id=null when branching from session start', async () => {
    const { api } = await import('../client')
    const { chatApi } = await import('../chat')

    vi.mocked(api.post).mockResolvedValueOnce({ id: 'branch-2' })
    await chatApi.branchSession('parent-1', null, 'From Scratch')

    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      '/api/chat/sessions/parent-1/branch',
      { fork_message_id: null, name: 'From Scratch' },
    )
  })

  it('returns the parsed ChatSessionDto from the response body', async () => {
    const { api } = await import('../client')
    const { chatApi } = await import('../chat')

    vi.mocked(api.post).mockResolvedValueOnce({
      id: 'branch-3',
      user_id: 'u1',
      persona_id: 'p1',
      title: 'Some Title',
      state: 'idle',
      tools_enabled: false,
      auto_read: false,
      reasoning_override: null,
      pinned: false,
      project_id: null,
      created_at: '2026-05-17T12:00:00Z',
      updated_at: '2026-05-17T12:00:00Z',
    })
    const result = await chatApi.branchSession('parent-1', 'assistant-7', 'Some Title')
    expect(result.id).toBe('branch-3')
    expect(result.title).toBe('Some Title')
  })
})
