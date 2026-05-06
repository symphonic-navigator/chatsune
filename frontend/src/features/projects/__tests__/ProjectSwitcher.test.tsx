// Snapshot + interaction tests for the in-chat project switcher.
// The picker dropdowns it composes are stubbed in the components
// imported here; the dedicated picker tests live alongside the
// picker files themselves.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { ProjectDto } from '../types'

vi.mock('../../../core/hooks/useViewport', () => ({
  useViewport: () => ({ isDesktop: true, isMobile: false }),
}))

// The picker components are exercised via their own tests; here we
// only need to verify which one mounts.
vi.mock('../ProjectPicker', () => ({
  ProjectPicker: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="picker-desktop">{sessionId}</div>
  ),
}))
vi.mock('../ProjectPickerMobile', () => ({
  ProjectPickerMobile: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="picker-mobile">{sessionId}</div>
  ),
}))

function makeProject(overrides: Partial<ProjectDto> = {}): ProjectDto {
  return {
    id: 'p1',
    user_id: 'u1',
    title: 'Star Trek Fan Fiction',
    emoji: '✨',
    description: null,
    nsfw: false,
    pinned: false,
    sort_order: 0,
    knowledge_library_ids: [],
    system_prompt: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ProjectSwitcher — no project assigned', () => {
  it('renders the unassigned chip with — and "No project"', async () => {
    const { ProjectSwitcher } = await import('../ProjectSwitcher')
    render(
      <ProjectSwitcher sessionId="sess-1" currentProjectId={null} />,
    )
    expect(screen.getByText('No project')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('disables the detail-open chip when no project is assigned', async () => {
    const onOpenDetail = vi.fn()
    const { ProjectSwitcher } = await import('../ProjectSwitcher')
    render(
      <ProjectSwitcher
        sessionId="sess-1"
        currentProjectId={null}
        onOpenDetail={onOpenDetail}
      />,
    )
    const chip = screen.getByRole('button', { name: /no project assigned/i })
    expect(chip).toBeDisabled()
    fireEvent.click(chip)
    expect(onOpenDetail).not.toHaveBeenCalled()
  })
})

describe('ProjectSwitcher — with project assigned', () => {
  it('renders the project emoji and title', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore
      .getState()
      .upsert(makeProject({ id: 'p-active', title: 'My Project', emoji: '🚀' }))

    const { ProjectSwitcher } = await import('../ProjectSwitcher')
    render(
      <ProjectSwitcher sessionId="sess-1" currentProjectId="p-active" />,
    )
    expect(screen.getByText('My Project')).toBeInTheDocument()
    expect(screen.getByText('🚀')).toBeInTheDocument()
  })

  it('invokes onOpenDetail with the project id when the chip is clicked', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(makeProject({ id: 'p-active' }))

    const onOpenDetail = vi.fn()
    const { ProjectSwitcher } = await import('../ProjectSwitcher')
    render(
      <ProjectSwitcher
        sessionId="sess-1"
        currentProjectId="p-active"
        onOpenDetail={onOpenDetail}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open star trek/i }))
    expect(onOpenDetail).toHaveBeenCalledWith('p-active')
  })
})

describe('ProjectSwitcher — picker toggling', () => {
  it('toggles the picker when the chevron is clicked', async () => {
    const { ProjectSwitcher } = await import('../ProjectSwitcher')
    render(
      <ProjectSwitcher sessionId="sess-X" currentProjectId={null} />,
    )
    expect(screen.queryByTestId('picker-desktop')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /switch project/i }))
    expect(screen.getByTestId('picker-desktop')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /close project picker/i }))
    expect(screen.queryByTestId('picker-desktop')).not.toBeInTheDocument()
  })
})

describe('ProjectSwitcher — active NSFW project in sanitised mode (§6.7)', () => {
  // Spec: "Active chat in NSFW-project, user toggles sanitised on:
  // chat stays open, top-bar switcher continues to display the
  // project. Sanitised filters discoverability, not active state."
  //
  // The switcher chip reads from the unfiltered ``useProjectsStore``
  // directly so the active project is always visible even when
  // ``useFilteredProjects`` would hide it from the picker list.
  it('keeps showing the chip for an NSFW project when sanitised mode is on', async () => {
    const { useProjectsStore } = await import('../useProjectsStore')
    useProjectsStore.getState().upsert(
      makeProject({
        id: 'p-spicy',
        title: 'Spicy Project',
        emoji: '🌶️',
        nsfw: true,
      }),
    )
    // Flip sanitised on at the global store level. The switcher must
    // still render the chip — only the picker contents (verified in
    // ProjectPicker.test.tsx) get filtered.
    const { useSanitisedMode } = await import(
      '../../../core/store/sanitisedModeStore'
    )
    useSanitisedMode.setState({ isSanitised: true })

    const { ProjectSwitcher } = await import('../ProjectSwitcher')
    render(
      <ProjectSwitcher sessionId="sess-1" currentProjectId="p-spicy" />,
    )

    expect(screen.getByText('Spicy Project')).toBeInTheDocument()
    expect(screen.getByText('🌶️')).toBeInTheDocument()

    // Reset for subsequent tests.
    useSanitisedMode.setState({ isSanitised: false })
  })
})
