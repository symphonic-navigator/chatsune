import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallPill } from '../ToolCallPill'

describe('ToolCallPill — streaming phase', () => {
  it('renders tool name and char count when known', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'streaming',
          toolName: 'search',
          charCount: 12,
          argsBuffer: '{"q":"hi"}',
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText('search')).toBeInTheDocument()
    expect(screen.getByText(/12 chars/)).toBeInTheDocument()
  })

  it('renders placeholder name before tool name is known', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'streaming',
          toolName: null,
          charCount: 0,
          argsBuffer: '',
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText('Tool')).toBeInTheDocument()
  })

  it('shows raw argsBuffer when expanded', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'streaming',
          toolName: 'f',
          charCount: 3,
          argsBuffer: '{"x',
          toolCallId: 'call_x',
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('{"x')).toBeInTheDocument()
  })
})

describe('ToolCallPill — executing phase', () => {
  it('renders friendly label for known tools', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'executing',
          toolName: 'web_search',
          arguments: { query: 'pizza' },
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText(/Searching the web for "pizza"/)).toBeInTheDocument()
  })

  it('renders generic label for unknown tools', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'executing',
          toolName: 'unknown_thing',
          arguments: {},
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText(/Running unknown_thing/)).toBeInTheDocument()
  })
})

describe('ToolCallPill — completed phase', () => {
  it('renders the display name and toggles Request/Response sections', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'completed',
          ref: {
            tool_call_id: 'call_x',
            tool_name: 'search',
            arguments: { query: 'pizza' },
            success: true,
            moderated_count: 0,
            result_content: '{"hits":3}',
          },
        }}
      />,
    )
    expect(screen.getByText('search')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Request')).toBeInTheDocument()
    expect(screen.getByText('Response')).toBeInTheDocument()
    expect(screen.getByText(/query: pizza/)).toBeInTheDocument()
    expect(screen.getByText('{"hits":3}')).toBeInTheDocument()
  })

  it('omits Response section when result_content is empty', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'completed',
          ref: {
            tool_call_id: 'call_x',
            tool_name: 'f',
            arguments: {},
            success: true,
            moderated_count: 0,
            result_content: null,
          },
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByText('Response')).toBeNull()
  })
})
