import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallPills } from '../ToolCallPills'
import type { ToolCallRef } from '../../../core/api/chat'

function makeRef(overrides: Partial<ToolCallRef> = {}): ToolCallRef {
  return {
    tool_call_id: 'tc-1',
    tool_name: 'gw__echo',
    arguments: { msg: 'hi' },
    success: true,
    result_content: null,
    ...overrides,
  }
}

describe('ToolCallPills', () => {
  it('renders Request and Response sections when result_content is set', () => {
    render(<ToolCallPills toolCalls={[makeRef({ result_content: 'echo: hi' })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Request')).toBeInTheDocument()
    expect(screen.getByText('Response')).toBeInTheDocument()
    expect(screen.getByText(/echo: hi/)).toBeInTheDocument()
    expect(screen.getByText(/msg: hi/)).toBeInTheDocument()
  })

  it('omits Response section when result_content is null', () => {
    render(<ToolCallPills toolCalls={[makeRef({ result_content: null })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Request')).toBeInTheDocument()
    expect(screen.queryByText('Response')).not.toBeInTheDocument()
  })

  it('renders Response on a failed call when result_content is set', () => {
    render(<ToolCallPills toolCalls={[makeRef({
      success: false,
      result_content: 'Error: boom',
    })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Response')).toBeInTheDocument()
    expect(screen.getByText(/Error: boom/)).toBeInTheDocument()
  })
})
