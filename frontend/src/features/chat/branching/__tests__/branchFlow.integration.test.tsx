import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import type { ChatSessionDto } from '../../../../core/api/chat'

// ---------------------------------------------------------------------------
// Mock chatApi.branchSession — the assertion target. The rest of the
// surface is left as-is; we don't transitively render ChatView here, only
// the BranchNameDialog wired into a minimal orchestrator so we can assert
// the click-through path: dialog confirm → API call → onClose + onBranch
// callback fires with the new session id, mirroring what ChatView does
// after navigate(...) is called.
const branchSessionMock = vi.fn(
  (
    _parentId: string,
    _forkMessageId: string | null,
    _name: string,
  ): Promise<ChatSessionDto> => {
    throw new Error('branchSessionMock not configured for this test')
  },
)

beforeEach(() => {
  branchSessionMock.mockReset()
})

import { BranchNameDialog } from '../BranchNameDialog'
import { useState } from 'react'

function fakeBranch(id: string, title: string): ChatSessionDto {
  return {
    id,
    user_id: 'u1',
    persona_id: 'p1',
    state: 'idle',
    title,
    tools_enabled: false,
    auto_read: false,
    reasoning_override: null,
    pinned: false,
    project_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
}

/**
 * Minimal orchestrator that mirrors what ChatView does for the branch
 * flow: open the BranchNameDialog with a fork id, await API confirm,
 * then notify the caller of the resulting branch id. Surfaced as its
 * own component so the integration test can simulate the click-through.
 */
function BranchFlowHarness({
  parentSessionId,
  forkMessageId,
  onSwitched,
  allSessions,
}: {
  parentSessionId: string
  forkMessageId: string | null
  onSwitched: (newSessionId: string) => void
  allSessions: ChatSessionDto[]
}) {
  const [open, setOpen] = useState(true)

  async function handleConfirm(name: string) {
    try {
      const result = await branchSessionMock(parentSessionId, forkMessageId, name)
      setOpen(false)
      onSwitched(result.id)
    } catch {
      // Mirrors ChatView's error path: dismiss the dialog and surface a
      // toast. The toast itself is out of scope for this integration
      // smoke test — we only assert that ``onSwitched`` is never called.
      setOpen(false)
    }
  }

  return (
    <BranchNameDialog
      isOpen={open}
      parentTitle="Parent"
      allSessions={allSessions}
      onConfirm={handleConfirm}
      onClose={() => setOpen(false)}
    />
  )
}

describe('branch flow integration', () => {
  it('confirming the dialog calls branchSession and notifies on success', async () => {
    branchSessionMock.mockResolvedValue(fakeBranch('branch-1', 'Parent (Variant 1)'))
    const onSwitched = vi.fn()
    render(
      <BranchFlowHarness
        parentSessionId="parent-1"
        forkMessageId="assistant-7"
        onSwitched={onSwitched}
        allSessions={[]}
      />,
    )
    // Pre-filled default name uses the parent title and Variant 1.
    const input = screen.getByTestId('branch-name-input') as HTMLInputElement
    expect(input.value).toBe('Parent (Variant 1)')

    await act(async () => {
      fireEvent.click(screen.getByTestId('branch-name-confirm'))
    })

    await waitFor(() => expect(onSwitched).toHaveBeenCalledWith('branch-1'))
    expect(branchSessionMock).toHaveBeenCalledWith(
      'parent-1',
      'assistant-7',
      'Parent (Variant 1)',
    )
    // Dialog dismisses on success.
    expect(screen.queryByTestId('branch-name-dialog')).not.toBeInTheDocument()
  })

  it('passes fork_message_id=null for branch-from-session-start', async () => {
    branchSessionMock.mockResolvedValue(fakeBranch('branch-2', 'Parent (Variant 1)'))
    render(
      <BranchFlowHarness
        parentSessionId="parent-1"
        forkMessageId={null}
        onSwitched={vi.fn()}
        allSessions={[]}
      />,
    )
    await act(async () => {
      fireEvent.click(screen.getByTestId('branch-name-confirm'))
    })
    await waitFor(() => expect(branchSessionMock).toHaveBeenCalled())
    expect(branchSessionMock).toHaveBeenCalledWith(
      'parent-1',
      null,
      'Parent (Variant 1)',
    )
  })

  it('keeps the user in the parent on API failure (no switch)', async () => {
    branchSessionMock.mockRejectedValueOnce(new Error('boom'))
    const onSwitched = vi.fn()
    render(
      <BranchFlowHarness
        parentSessionId="parent-1"
        forkMessageId="assistant-7"
        onSwitched={onSwitched}
        allSessions={[]}
      />,
    )
    await act(async () => {
      fireEvent.click(screen.getByTestId('branch-name-confirm'))
    })
    // Wait for the rejected promise to settle — the harness does not
    // call onSwitched on failure.
    await waitFor(() => expect(branchSessionMock).toHaveBeenCalled())
    expect(onSwitched).not.toHaveBeenCalled()
  })
})
