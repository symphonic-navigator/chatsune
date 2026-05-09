import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ThinkingButton } from '../buttons/ThinkingButton'
import type { ReasoningCapability } from '@/core/types/llm'

const optional: ReasoningCapability = {
  kind: 'optional',
  effort: null,
  default_on: true,
}
const optionalWithEffort: ReasoningCapability = {
  kind: 'optional',
  effort: { buckets: ['low', 'medium', 'high'], default_bucket: 'medium' },
  default_on: true,
}
const alwaysOn: ReasoningCapability = {
  kind: 'always_on',
  effort: null,
  default_on: true,
}
const noReasoning: ReasoningCapability = {
  kind: 'no_reasoning',
  effort: null,
  default_on: false,
}

const noop = async () => {}

describe('ThinkingButton', () => {
  it('disabled-inactive for no_reasoning', () => {
    render(
      <ThinkingButton
        reasoning={noReasoning}
        mode="off"
        effort={null}
        onChange={noop}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('data-state', 'inactive')
  })

  it('disabled-active for always_on', () => {
    render(
      <ThinkingButton
        reasoning={alwaysOn}
        mode="on"
        effort={null}
        onChange={noop}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('data-state', 'active')
  })

  it('toggle for optional without effort', async () => {
    let captured: { mode: string; effort: string | null } | null = null
    render(
      <ThinkingButton
        reasoning={optional}
        mode="off"
        effort={null}
        onChange={async (m, e) => {
          captured = { mode: m, effort: e }
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    await new Promise((r) => setTimeout(r, 0))
    expect(captured).toEqual({ mode: 'on', effort: null })
  })

  it('opens pop-out for optional with effort', () => {
    render(
      <ThinkingButton
        reasoning={optionalWithEffort}
        mode="on"
        effort="medium"
        onChange={noop}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('menuitemradio', { name: /^Off$/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitemradio', { name: /^Low$/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitemradio', { name: /^Medium$/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitemradio', { name: /^High$/ })).toBeInTheDocument()
  })

  it('selecting Off in pop-out commits mode=off', async () => {
    let captured: { mode: string; effort: string | null } | null = null
    render(
      <ThinkingButton
        reasoning={optionalWithEffort}
        mode="on"
        effort="medium"
        onChange={async (m, e) => {
          captured = { mode: m, effort: e }
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    fireEvent.click(screen.getByRole('menuitemradio', { name: /^Off$/ }))
    await new Promise((r) => setTimeout(r, 0))
    expect(captured).toEqual({ mode: 'off', effort: null })
  })

  it('selecting a bucket in pop-out commits mode=on with that effort', async () => {
    let captured: { mode: string; effort: string | null } | null = null
    render(
      <ThinkingButton
        reasoning={optionalWithEffort}
        mode="off"
        effort={null}
        onChange={async (m, e) => {
          captured = { mode: m, effort: e }
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    fireEvent.click(screen.getByRole('menuitemradio', { name: /^High$/ }))
    await new Promise((r) => setTimeout(r, 0))
    expect(captured).toEqual({ mode: 'on', effort: 'high' })
  })
})
