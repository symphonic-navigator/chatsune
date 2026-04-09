import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('../../../../core/api/jobsLog', () => ({
  fetchJobLog: async () => [
    {
      entry_id: 'a',
      job_id: 'j1',
      job_type: 'memory_extraction',
      persona_id: 'p1',
      status: 'completed',
      attempt: 0,
      silent: false,
      ts: new Date().toISOString(),
      duration_ms: 1234,
      error_message: null,
    },
    {
      entry_id: 'b',
      job_id: 'j2',
      job_type: 'title_generation',
      persona_id: null,
      status: 'completed',
      attempt: 0,
      silent: true,
      ts: new Date().toISOString(),
      duration_ms: 500,
      error_message: null,
    },
  ],
}))

vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: [{ id: 'p1', name: 'Aria' }] }),
}))

vi.mock('../../../../core/websocket/eventBus', () => ({
  eventBus: { on: () => () => {} },
}))

import { JobLogTab } from '../JobLogTab'

describe('JobLogTab', () => {
  it('hides silent entries by default and shows them when toggled', async () => {
    render(<JobLogTab />)
    expect(await screen.findByText('Memory extraction')).toBeInTheDocument()
    expect(screen.queryByText('Title generation')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTitle(/silent jobs/i))
    expect(await screen.findByText('Title generation')).toBeInTheDocument()
  })
})
