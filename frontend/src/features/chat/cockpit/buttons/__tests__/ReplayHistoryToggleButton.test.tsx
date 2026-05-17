import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ReplayHistoryToggleButton } from '../ReplayHistoryToggleButton'
import { useCockpitStore } from '../../cockpitStore'

// Patch the API so ``updateExtras`` resolves without a real HTTP call.
vi.mock('@/core/api/chat', async () => {
  const actual = await vi.importActual<typeof import('@/core/api/chat')>(
    '@/core/api/chat',
  )
  return {
    ...actual,
    chatApi: {
      ...actual.chatApi,
      updateSessionExtras: vi.fn().mockResolvedValue({
        tools_enabled: false,
        reasoning_mode: 'off',
        reasoning_effort: null,
        replay_tool_history: true,
      }),
    },
  }
})

import { chatApi } from '@/core/api/chat'

const SID = 'session-replay-test'

function hydrate(replay: boolean) {
  useCockpitStore.getState().hydrateFromServer(SID, {
    extras: {
      tools_enabled: false,
      reasoning_mode: 'off',
      reasoning_effort: null,
      replay_tool_history: replay,
    },
    autoRead: false,
  })
}

describe('ReplayHistoryToggleButton', () => {
  beforeEach(() => {
    useCockpitStore.setState({ bySession: {}, pendingAutoReadMessageId: null })
    vi.clearAllMocks()
  })

  it('renders the active variant when replay_tool_history is on', () => {
    hydrate(true)
    render(<ReplayHistoryToggleButton sessionId={SID} />)
    const btn = screen.getByRole('button', { name: /tool history replay: on/i })
    expect(btn).toHaveAttribute('data-state', 'active')
  })

  it('renders the idle variant when replay_tool_history is off', () => {
    hydrate(false)
    render(<ReplayHistoryToggleButton sessionId={SID} />)
    const btn = screen.getByRole('button', { name: /tool history replay: off/i })
    expect(btn).toHaveAttribute('data-state', 'inactive')
  })

  it('PATCHes the negated value on click', async () => {
    hydrate(true)
    render(<ReplayHistoryToggleButton sessionId={SID} />)
    fireEvent.click(screen.getByRole('button'))
    // Let the optimistic update + the awaited PATCH settle.
    await act(() => Promise.resolve())
    expect(chatApi.updateSessionExtras).toHaveBeenCalledTimes(1)
    expect(chatApi.updateSessionExtras).toHaveBeenCalledWith(
      SID,
      expect.objectContaining({ replay_tool_history: false }),
    )
    // The optimistic update should already have flipped the local state.
    expect(
      useCockpitStore.getState().bySession[SID].extras.replay_tool_history,
    ).toBe(false)
  })

  it('shows the "applies from next response" hint for ~3s after click', () => {
    vi.useFakeTimers()
    try {
      hydrate(true)
      render(<ReplayHistoryToggleButton sessionId={SID} />)
      // No hint before click.
      expect(screen.queryByRole('status')).toBeNull()
      fireEvent.click(screen.getByRole('button'))
      const hint = screen.getByRole('status')
      expect(hint.textContent).toMatch(/applies from next response/i)
      // Advance time past the timeout — hint should disappear.
      act(() => {
        vi.advanceTimersByTime(3001)
      })
      expect(screen.queryByRole('status')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
