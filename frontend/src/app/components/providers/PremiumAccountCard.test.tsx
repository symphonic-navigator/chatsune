import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PremiumAccountCard } from './PremiumAccountCard'
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
} from '../../../core/types/providers'

const definition: PremiumProviderDefinition = {
  id: 'xai',
  display_name: 'xAI',
  icon: 'xai',
  base_url: 'https://api.x.ai',
  capabilities: ['llm', 'tts'],
  config_fields: [],
  linked_integrations: ['xai_voice'],
}

describe('PremiumAccountCard', () => {
  it('shows "not set" when account is null', () => {
    render(
      <PremiumAccountCard
        definition={definition}
        account={null}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
      />,
    )
    expect(screen.getByText('not set')).toBeInTheDocument()
  })

  it('calls onSave with the api_key when Save clicked', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <PremiumAccountCard
        definition={definition}
        account={null}
        onSave={onSave}
        onDelete={vi.fn()}
        onTest={vi.fn()}
      />,
    )
    const input = screen.getByPlaceholderText('API key')
    fireEvent.change(input, { target: { value: 'xai-abc' } })
    fireEvent.click(screen.getByText('Save'))
    expect(onSave).toHaveBeenCalledWith({ api_key: 'xai-abc' })
  })

  it('shows Change / Test / Remove when configured', () => {
    const account: PremiumProviderAccount = {
      provider_id: 'xai',
      config: { api_key: { is_set: true } },
      last_test_status: 'ok',
      last_test_error: null,
      last_test_at: null,
    }
    render(
      <PremiumAccountCard
        definition={definition}
        account={account}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
      />,
    )
    expect(screen.getByText('Change')).toBeInTheDocument()
    expect(screen.getByText('Test')).toBeInTheDocument()
    expect(screen.getByText('Remove')).toBeInTheDocument()
  })
})
