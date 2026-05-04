// Tests for the Project-Detail-Overlay shell. Covers the spec-mandated
// invariants: opens with the requested initial tab, closes on Escape,
// closes on backdrop click, and switches tabs when the user clicks the
// tab strip.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ProjectDto } from '../types'

// Stub the four shared user-modal tabs so this file doesn't pull in
// their full dependency trees (HistoryTab + chat hooks, GalleryGrid +
// images store, etc). The overlay's job is to mount the right
// component for the active tab — which component is tested below.
vi.mock('../../../app/components/user-modal/HistoryTab', () => ({
  HistoryTab: ({ projectFilter }: { projectFilter?: string }) => (
    <div data-testid="history-tab">history:{projectFilter ?? ''}</div>
  ),
}))
vi.mock('../../../app/components/user-modal/UploadsTab', () => ({
  UploadsTab: ({ projectFilter }: { projectFilter?: string }) => (
    <div data-testid="uploads-tab">uploads:{projectFilter ?? ''}</div>
  ),
}))
vi.mock('../../../app/components/user-modal/ArtefactsTab', () => ({
  ArtefactsTab: ({ projectFilter }: { projectFilter?: string }) => (
    <div data-testid="artefacts-tab">artefacts:{projectFilter ?? ''}</div>
  ),
}))
vi.mock('../../../app/components/user-modal/ImagesTab', () => ({
  ImagesTab: ({ projectFilter }: { projectFilter?: string }) => (
    <div data-testid="images-tab">images:{projectFilter ?? ''}</div>
  ),
}))

// Stub the back-button hook — its real implementation pulls in the
// router context which we don't render here.
vi.mock('../../../core/hooks/useBackButtonClose', () => ({
  useBackButtonClose: () => {},
}))

// Project store — we expose just enough surface for the overlay.
const projectsState = {
  value: {
    'p1': {
      id: 'p1',
      user_id: 'u1',
      title: 'Star Trek Fan Fiction',
      emoji: '🖖',
      description: null,
      nsfw: false,
      pinned: true,
      sort_order: 0,
      knowledge_library_ids: [],
      created_at: '2026-05-01T00:00:00Z',
      updated_at: '2026-05-01T00:00:00Z',
    } as ProjectDto,
  } as Record<string, ProjectDto>,
}
vi.mock('../useProjectsStore', () => ({
  useProjectsStore: (sel: (s: { projects: Record<string, ProjectDto> }) => unknown) =>
    sel({ projects: projectsState.value }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  projectsState.value = {
    'p1': {
      id: 'p1',
      user_id: 'u1',
      title: 'Star Trek Fan Fiction',
      emoji: '🖖',
      description: null,
      nsfw: false,
      pinned: true,
      sort_order: 0,
      knowledge_library_ids: [],
      created_at: '2026-05-01T00:00:00Z',
      updated_at: '2026-05-01T00:00:00Z',
    },
  }
})

describe('ProjectDetailOverlay shell', () => {
  it('renders with the requested initial tab and the project header', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    const onClose = vi.fn()
    render(
      <ProjectDetailOverlay
        projectId="p1"
        onClose={onClose}
        initialTab="chats"
      />,
    )
    expect(screen.getByTestId('project-detail-overlay')).toBeInTheDocument()
    expect(screen.getByText('Star Trek Fan Fiction')).toBeInTheDocument()
    expect(screen.getByTestId('history-tab')).toHaveTextContent('history:p1')
  })

  it('defaults to the overview tab when no initialTab is supplied', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    render(
      <ProjectDetailOverlay projectId="p1" onClose={vi.fn()} />,
    )
    expect(screen.getByTestId('project-overview-tab')).toBeInTheDocument()
  })

  it('switches to the personas tab when the personas pill is clicked', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    render(
      <ProjectDetailOverlay projectId="p1" onClose={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('tab', { name: 'Personas' }))
    expect(screen.getByTestId('project-personas-tab')).toBeInTheDocument()
  })

  it('mounts the four shared tabs with the project filter', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    render(
      <ProjectDetailOverlay projectId="p1" onClose={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('tab', { name: 'Chats' }))
    expect(screen.getByTestId('history-tab')).toHaveTextContent('history:p1')
    fireEvent.click(screen.getByRole('tab', { name: 'Uploads' }))
    expect(screen.getByTestId('uploads-tab')).toHaveTextContent('uploads:p1')
    fireEvent.click(screen.getByRole('tab', { name: 'Artefacts' }))
    expect(screen.getByTestId('artefacts-tab')).toHaveTextContent('artefacts:p1')
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    expect(screen.getByTestId('images-tab')).toHaveTextContent('images:p1')
  })

  it('closes on Escape', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    const onClose = vi.fn()
    render(
      <ProjectDetailOverlay projectId="p1" onClose={onClose} />,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes when the close button is clicked', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    const onClose = vi.fn()
    render(
      <ProjectDetailOverlay projectId="p1" onClose={onClose} />,
    )
    fireEvent.click(screen.getByLabelText(/close project overlay/i))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes when the backdrop is clicked', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    const onClose = vi.fn()
    const { container } = render(
      <ProjectDetailOverlay projectId="p1" onClose={onClose} />,
    )
    // Backdrop is the first absolutely-positioned div with
    // pointer-events; aria-hidden lets us locate it deterministically.
    const backdrop = container.querySelector('[aria-hidden="true"]')
    expect(backdrop).not.toBeNull()
    if (backdrop) fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes when the backing project is removed from the store', async () => {
    const { ProjectDetailOverlay } = await import('../ProjectDetailOverlay')
    const onClose = vi.fn()
    projectsState.value = {}
    render(
      <ProjectDetailOverlay projectId="missing" onClose={onClose} />,
    )
    expect(onClose).toHaveBeenCalled()
  })
})
