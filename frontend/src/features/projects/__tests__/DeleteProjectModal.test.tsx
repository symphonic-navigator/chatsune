// Behaviour tests for DeleteProjectModal — spec §9. The modal's job
// is small but load-bearing:
//   1. Mount-time fetch of usage counts.
//   2. Render counts; render a placeholder when usage is unavailable.
//   3. Toggle between safe-delete and full-purge based on the
//      checkbox state, with matching button label.
//   4. Submit calls projectsApi.delete with the right ``purgeData``
//      flag.
//   5. Cancel closes without action.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { ProjectWithUsage } from '../types'

vi.mock('../projectsApi', () => ({
  projectsApi: {
    get: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: (sel: (s: { addNotification: () => void }) => unknown) =>
    sel({ addNotification: vi.fn() }),
}))

function makeProjectWithUsage(
  overrides: Partial<ProjectWithUsage> = {},
): ProjectWithUsage {
  return {
    id: 'p-trek',
    user_id: 'u1',
    title: 'Star Trek Fan Fiction',
    emoji: '✨',
    description: null,
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    usage: {
      chat_count: 14,
      upload_count: 8,
      artefact_count: 23,
      image_count: 6,
    },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('DeleteProjectModal — render & counts', () => {
  it('renders the heading with the project title', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())

    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={() => {}}
      />,
    )
    expect(
      screen.getByText(/delete project "star trek fan fiction"/i),
    ).toBeInTheDocument()
  })

  it('fetches usage counts on mount and renders them', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())

    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={() => {}}
      />,
    )

    expect(vi.mocked(projectsApi.get)).toHaveBeenCalledWith('p-trek', true)

    await waitFor(() => {
      expect(
        screen.getByTestId('delete-project-purge-counts'),
      ).toHaveTextContent(/14 chats · 8 uploads · 23 artefacts · 6 images/)
    })
    expect(
      screen.getByTestId('delete-project-safe-summary'),
    ).toHaveTextContent(/14 chats will return to your global history/)
  })

  it('falls back to a placeholder when usage fetch fails', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockRejectedValueOnce(new Error('boom'))

    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={() => {}}
      />,
    )
    await waitFor(() => {
      expect(
        screen.getByTestId('delete-project-usage-error'),
      ).toBeInTheDocument()
    })
  })
})

describe('DeleteProjectModal — purge toggle', () => {
  it('starts with the purge checkbox off and shows the safe-delete label', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())

    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={() => {}}
      />,
    )
    const checkbox = screen.getByTestId('delete-project-purge-toggle')
    expect((checkbox as HTMLInputElement).checked).toBe(false)
    expect(screen.getByTestId('delete-project-submit')).toHaveTextContent(
      /^delete project$/i,
    )
  })

  it('switches to "Delete project + all data" when the checkbox is on', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())

    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('delete-project-purge-toggle'))
    expect(screen.getByTestId('delete-project-submit')).toHaveTextContent(
      /delete project \+ all data/i,
    )
  })
})

describe('DeleteProjectModal — submit & cancel', () => {
  it('calls delete(id, false) when checkbox is off', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())
    vi.mocked(projectsApi.delete).mockResolvedValueOnce({ ok: true })

    const onClose = vi.fn()
    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={onClose}
      />,
    )
    await waitFor(() =>
      expect(screen.getByTestId('delete-project-purge-counts')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId('delete-project-submit'))

    await waitFor(() =>
      expect(vi.mocked(projectsApi.delete)).toHaveBeenCalledWith('p-trek', false),
    )
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('calls delete(id, true) when checkbox is on', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())
    vi.mocked(projectsApi.delete).mockResolvedValueOnce({ ok: true })

    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={() => {}}
      />,
    )
    await waitFor(() =>
      expect(screen.getByTestId('delete-project-purge-counts')).toBeInTheDocument(),
    )
    fireEvent.click(screen.getByTestId('delete-project-purge-toggle'))
    fireEvent.click(screen.getByTestId('delete-project-submit'))

    await waitFor(() =>
      expect(vi.mocked(projectsApi.delete)).toHaveBeenCalledWith('p-trek', true),
    )
  })

  it('Cancel closes the modal without calling delete', async () => {
    const { projectsApi } = await import('../projectsApi')
    vi.mocked(projectsApi.get).mockResolvedValueOnce(makeProjectWithUsage())

    const onClose = vi.fn()
    const { DeleteProjectModal } = await import('../DeleteProjectModal')
    render(
      <DeleteProjectModal
        isOpen={true}
        projectId="p-trek"
        projectTitle="Star Trek Fan Fiction"
        onClose={onClose}
      />,
    )
    fireEvent.click(screen.getByTestId('delete-project-cancel'))
    expect(onClose).toHaveBeenCalled()
    expect(vi.mocked(projectsApi.delete)).not.toHaveBeenCalled()
  })
})
