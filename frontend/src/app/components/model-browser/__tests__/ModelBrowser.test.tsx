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
  groups: Array<{
    connection: Connection
    status: 'loading' | 'ready' | 'error'
    error?: string
    models: EnrichedModelDto[]
  }>
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
        status: 'ready',
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
        status: 'ready',
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

describe('ModelBrowser — per-group loading', () => {
  it('renders a spinner inside a group whose status is loading', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1', display_name: 'Slow Co', slug: 'slow' }),
        status: 'loading',
        models: [],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByTestId('group-loading-c1')).toBeInTheDocument()
    expect(screen.queryByText(/No models listed/i)).toBeNull()
  })
})

describe('ModelBrowser — per-group error', () => {
  it('renders the error message and retry hint when a group has status error', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1', display_name: 'Broken' }),
        status: 'error',
        error: 'upstream 503',
        models: [],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    const node = screen.getByTestId('group-error-c1')
    expect(node).toBeInTheDocument()
    expect(node).toHaveTextContent('upstream 503')
    expect(node).toHaveTextContent(/retry/i)
  })
})

describe('ModelBrowser — filter pipeline keeps non-ready groups', () => {
  it('keeps a loading group visible even when models are empty', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1', display_name: 'LoadingCo' }),
        status: 'loading',
        models: [],
      },
      {
        connection: makeConnection({ id: 'c2', display_name: 'ErrorCo' }),
        status: 'error',
        error: 'oops',
        models: [],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByTestId('group-loading-c1')).toBeInTheDocument()
    expect(screen.getByTestId('group-error-c2')).toBeInTheDocument()
  })
})

describe('ModelBrowser — filter bar gating', () => {
  it('hides the filter bar during phase A', async () => {
    hubState.groups = []
    hubState.loading = true

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.queryByPlaceholderText(/search model name/i)).toBeNull()
  })

  it('shows the filter bar once groups are present', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1' }),
        status: 'ready',
        models: [],
      },
    ]
    hubState.loading = false

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByPlaceholderText(/search model name/i)).toBeInTheDocument()
  })
})

describe('ModelBrowser — phase A placeholder', () => {
  it('shows a spinner placeholder while groups are still being listed', async () => {
    hubState.groups = []
    hubState.loading = true
    hubState.error = null

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByTestId('model-browser-phase-a')).toBeInTheDocument()
  })

  it('shows the empty-connections hint only when not loading and no groups', async () => {
    hubState.groups = []
    hubState.loading = false
    hubState.error = null

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.queryByTestId('model-browser-phase-a')).toBeNull()
    expect(screen.getByText(/No LLM connection configured/i)).toBeInTheDocument()
  })
})
