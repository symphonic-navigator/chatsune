import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AboutMeTab } from './AboutMeTab'

vi.mock('../../../core/api/meApi', () => ({
  meApi: {
    getAboutMe: vi.fn().mockResolvedValue({ about_me: null }),
    updateAboutMe: vi.fn().mockResolvedValue({ about_me: null }),
    updateDisplayName: vi.fn().mockResolvedValue({
      id: '1',
      username: 'chris',
      email: 'chris@example.com',
      display_name: 'New Name',
      role: 'user',
      is_active: true,
      must_change_password: false,
      created_at: '',
      updated_at: '',
    }),
  },
}))

vi.mock('../../../core/store/authStore', () => ({
  useAuthStore: (sel?: (s: Record<string, unknown>) => unknown) => {
    const state = { user: { display_name: 'Chris', username: 'chris', role: 'user' } }
    return sel ? sel(state) : state
  },
}))

function renderInRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('AboutMeTab — display name field', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders display name input with value from auth store', async () => {
    renderInRouter(<AboutMeTab />)
    const input = await screen.findByLabelText(/display name/i, { selector: 'input' })
    expect(input).toHaveValue('Chris')
  })

  it('calls updateDisplayName with the new value on save', async () => {
    const { meApi } = await import('../../../core/api/meApi')
    renderInRouter(<AboutMeTab />)

    const input = await screen.findByLabelText(/display name/i, { selector: 'input' })
    await userEvent.clear(input)
    await userEvent.type(input, 'New Name')

    const saveBtn = screen.getByRole('button', { name: /save display name/i })
    await userEvent.click(saveBtn)

    await waitFor(() => {
      expect(meApi.updateDisplayName).toHaveBeenCalledWith('New Name')
    })
  })
})
