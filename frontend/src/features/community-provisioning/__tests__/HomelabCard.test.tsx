import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HomelabCard } from '../HomelabCard'
import type { Homelab } from '../types'

// Mock ApiKeyList (not the subject under test) — keeps this test focused on
// the card's own output.
vi.mock('../ApiKeyList', () => ({ ApiKeyList: () => null }))
vi.mock('../HostKeyRevealModal', () => ({ HostKeyRevealModal: () => null }))
vi.mock('../HomelabEditModal', () => ({ HomelabEditModal: () => null }))

const sample: Homelab = {
  homelab_id: 'Xk7bQ2eJn9m',
  display_name: 'Wohnzimmer-GPU',
  host_key_hint: '9f2a',
  status: 'active',
  created_at: '2026-04-16T10:00:00Z',
  last_seen_at: null,
  last_sidecar_version: null,
  last_engine_info: null,
  is_online: false,
  max_concurrent_requests: 3,
  host_slug: 'wohnzimmer-gpu',
}

describe('HomelabCard', () => {
  it('renders display name, homelab id, host-key hint, and offline badge', () => {
    render(<HomelabCard homelab={sample} />)
    expect(screen.getByText('Wohnzimmer-GPU')).toBeInTheDocument()
    expect(screen.getByText('Xk7bQ2eJn9m')).toBeInTheDocument()
    expect(screen.getByText('9f2a')).toBeInTheDocument()
    expect(screen.getByText('offline')).toBeInTheDocument()
  })

  it('shows online badge when is_online=true', () => {
    render(<HomelabCard homelab={{ ...sample, is_online: true }} />)
    expect(screen.getByText('online')).toBeInTheDocument()
  })

  it('shows engine info when available', () => {
    render(
      <HomelabCard
        homelab={{
          ...sample,
          last_engine_info: { type: 'ollama', version: '0.5.1' },
          last_sidecar_version: '1.0.0',
        }}
      />,
    )
    expect(screen.getByText('ollama')).toBeInTheDocument()
    expect(screen.getByText(/0\.5\.1/)).toBeInTheDocument()
    expect(screen.getByText(/1\.0\.0/)).toBeInTheDocument()
  })
})
