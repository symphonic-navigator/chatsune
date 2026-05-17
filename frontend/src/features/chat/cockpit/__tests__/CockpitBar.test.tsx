import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ReasoningToolsCluster } from '../ReasoningToolsCluster'
import type { ResolvedCapabilities } from '@/core/types/llm'
import type { ChatSessionExtras } from '@/core/api/chat'

// Mutex-on, optional-reasoning model. Tools and reasoning cannot run
// together — selecting one must deactivate the other in the same patch.
const mutexOptionalCap: ResolvedCapabilities = {
  reasoning: { kind: 'optional', effort: null, default_on: true },
  tools: { supported: true, exclusive_with_reasoning: true },
  first_class_support: true,
}

const independentCap: ResolvedCapabilities = {
  reasoning: { kind: 'optional', effort: null, default_on: true },
  tools: { supported: true, exclusive_with_reasoning: false },
  first_class_support: true,
}

describe('ReasoningToolsCluster mutex coordination', () => {
  it('clicking Tools deactivates Reasoning when mutex', async () => {
    const updates: Partial<ChatSessionExtras>[] = []
    render(
      <ReasoningToolsCluster
        capability={mutexOptionalCap}
        extras={{
          tools_enabled: false,
          reasoning_mode: 'on',
          reasoning_effort: null,
          replay_tool_history: true,
        }}
        onUpdate={async (patch) => {
          updates.push(patch)
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /tools/i }))
    await new Promise((r) => setTimeout(r, 0))
    expect(updates[0]).toMatchObject({
      tools_enabled: true,
      reasoning_mode: 'off',
      reasoning_effort: null,
    })
  })

  it('clicking Thinking deactivates Tools when mutex', async () => {
    const updates: Partial<ChatSessionExtras>[] = []
    render(
      <ReasoningToolsCluster
        capability={mutexOptionalCap}
        extras={{
          tools_enabled: true,
          reasoning_mode: 'off',
          reasoning_effort: null,
          replay_tool_history: true,
        }}
        onUpdate={async (patch) => {
          updates.push(patch)
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /thinking/i }))
    await new Promise((r) => setTimeout(r, 0))
    expect(updates[0]).toMatchObject({
      reasoning_mode: 'on',
      tools_enabled: false,
    })
  })

  it('clicking active Tools turns it off without touching reasoning', async () => {
    const updates: Partial<ChatSessionExtras>[] = []
    render(
      <ReasoningToolsCluster
        capability={mutexOptionalCap}
        extras={{
          tools_enabled: true,
          reasoning_mode: 'off',
          reasoning_effort: null,
          replay_tool_history: true,
        }}
        onUpdate={async (patch) => {
          updates.push(patch)
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /tools/i }))
    await new Promise((r) => setTimeout(r, 0))
    expect(updates[0]).toMatchObject({ tools_enabled: false })
    expect(updates[0]).not.toHaveProperty('reasoning_mode')
  })

  it('mutex left alone when capability does not require it', async () => {
    const updates: Partial<ChatSessionExtras>[] = []
    render(
      <ReasoningToolsCluster
        capability={independentCap}
        extras={{
          tools_enabled: false,
          reasoning_mode: 'on',
          reasoning_effort: null,
          replay_tool_history: true,
        }}
        onUpdate={async (patch) => {
          updates.push(patch)
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /tools/i }))
    await new Promise((r) => setTimeout(r, 0))
    expect(updates[0]).toMatchObject({ tools_enabled: true })
    expect(updates[0]).not.toHaveProperty('reasoning_mode')
  })

  it('renders Tools as disabled when not supported', () => {
    render(
      <ReasoningToolsCluster
        capability={{
          reasoning: { kind: 'optional', effort: null, default_on: true },
          tools: { supported: false, exclusive_with_reasoning: false },
          first_class_support: true,
        }}
        extras={{
          tools_enabled: false,
          reasoning_mode: 'off',
          reasoning_effort: null,
          replay_tool_history: true,
        }}
        onUpdate={async () => {}}
      />,
    )
    const toolsBtn = screen.getByRole('button', { name: /tools/i })
    expect(toolsBtn).toBeDisabled()
  })
})
