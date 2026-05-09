// Behaviour tests for the ModelBrowser first-class indicator.
// Covers (a) the inline badge that surfaces ``first_class_support`` and
// (b) the "First-class only" toolbar filter that hides best-effort rows.
//
// The hub hook (``useEnrichedModels``) and any network APIs are mocked
// so the component renders deterministically from a fixed model list.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type {
  Connection,
  EnrichedModelDto,
} from '../../../../core/types/llm'

vi.mock('../../../../core/api/llm', () => ({
  llmApi: {
    listConnections: vi.fn(),
    listUserModelConfigs: vi.fn(),
    listConnectionModels: vi.fn(),
    refreshConnectionModels: vi.fn(),
    setUserModelConfig: vi.fn(),
  },
}))

vi.mock('../../../../core/api/providers', () => ({
  providersApi: {
    catalogue: vi.fn(),
    listAccounts: vi.fn(),
    listProviderModels: vi.fn(),
    refreshProviderModels: vi.fn(),
  },
}))

const hubState: {
  groups: Array<{ connection: Connection; models: EnrichedModelDto[] }>
  loading: boolean
  error: string | null
} = {
  groups: [],
  loading: false,
  error: null,
}

vi.mock('../../../../core/hooks/useEnrichedModels', () => ({
  useEnrichedModels: () => ({
    groups: hubState.groups,
    loading: hubState.loading,
    error: hubState.error,
    refresh: vi.fn(async () => {}),
    findByUniqueId: (uid: string) => {
      for (const g of hubState.groups) {
        const m = g.models.find((x) => x.unique_id === uid)
        if (m) return m
      }
      return null
    },
  }),
}))

function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c1',
    user_id: 'u1',
    adapter_type: 'ollama_http',
    display_name: 'Test Conn',
    slug: 'conn',
    config: {},
    last_test_status: 'valid',
    last_test_error: null,
    last_test_at: null,
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    is_system_managed: false,
    ...overrides,
  }
}

function makeModel(
  uniqueId: string,
  displayName: string,
  firstClass: boolean,
  overrides: Partial<EnrichedModelDto> = {},
): EnrichedModelDto {
  return {
    connection_id: 'c1',
    connection_slug: 'conn',
    connection_display_name: 'Test Conn',
    model_id: uniqueId.includes(':') ? uniqueId.split(':').slice(1).join(':') : uniqueId,
    display_name: displayName,
    context_window: 8000,
    supports_reasoning: true,
    supports_vision: false,
    supports_tool_calls: true,
    reasoning: { kind: 'optional', effort: null, default_on: true },
    tools: { supported: true, exclusive_with_reasoning: false },
    first_class_support: firstClass,
    parameter_count: null,
    raw_parameter_count: null,
    quantisation_level: null,
    unique_id: uniqueId,
    user_config: null,
    ...overrides,
  }
}

beforeEach(() => {
  hubState.groups = []
  hubState.loading = false
  hubState.error = null
  vi.clearAllMocks()
  // Reset persisted store state between tests (the store loads from
  // localStorage at module import). The setup file already calls
  // localStorage.clear() and vi.resetModules() — that combination ensures
  // the store re-initialises with a clean ``firstClassOnly`` value.
})

describe('ModelBrowser — first-class badge', () => {
  it('renders the badge on first-class rows and nothing on best-effort rows', async () => {
    hubState.groups = [
      {
        connection: makeConnection(),
        models: [
          makeModel('conn:m1', 'Model One', true),
          makeModel('conn:m2', 'Model Two', false),
        ],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(
      screen.getByTestId('first-class-badge-conn:m1'),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId('first-class-badge-conn:m2'),
    ).toBeNull()
  })
})

describe('ModelBrowser — first-class filter', () => {
  it('hides best-effort rows when "First-class only" is enabled', async () => {
    hubState.groups = [
      {
        connection: makeConnection(),
        models: [
          makeModel('conn:m1', 'First Class Model', true),
          makeModel('conn:m2', 'Best Effort Model', false),
        ],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    // Both visible initially.
    expect(screen.getByText('First Class Model')).toBeInTheDocument()
    expect(screen.getByText('Best Effort Model')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText(/first-class only/i))

    expect(screen.getByText('First Class Model')).toBeInTheDocument()
    expect(screen.queryByText('Best Effort Model')).toBeNull()
  })
})
