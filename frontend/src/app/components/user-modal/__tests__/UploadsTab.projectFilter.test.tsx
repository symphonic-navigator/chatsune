// Mindspace projectFilter wiring for UploadsTab. Verifies the
// listFiles API call carries the project_id query param when the
// prop is set.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { StorageFileDto, StorageQuotaDto } from '../../../../core/api/storage'
import type { PersonaDto } from '../../../../core/types/persona'

const listFilesMock = vi.fn(
  async (): Promise<StorageFileDto[]> => [],
)
const getQuotaMock = vi.fn(
  async (): Promise<StorageQuotaDto> => ({
    used_bytes: 0,
    limit_bytes: 1,
    percentage: 0,
  }),
)

vi.mock('../../../../core/api/storage', () => ({
  storageApi: {
    listFiles: (...args: unknown[]) => listFilesMock(...args),
    getQuota: () => getQuotaMock(),
    downloadUrl: (id: string) => `/api/storage/files/${id}/download`,
    renameFile: vi.fn(),
    deleteFile: vi.fn(),
  },
}))

vi.mock('../../../../core/api/client', () => ({
  currentAccessToken: () => null,
}))

const personasState = { value: [] as PersonaDto[] }
vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: personasState.value }),
}))

vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: () => ({ isSanitised: false }),
}))

beforeEach(() => {
  vi.clearAllMocks()
  personasState.value = []
})

describe('UploadsTab — projectFilter', () => {
  it('passes project_id to storageApi.listFiles', async () => {
    const { UploadsTab } = await import('../UploadsTab')
    render(<UploadsTab projectFilter="proj-trek" />)
    await Promise.resolve()
    await Promise.resolve()
    expect(listFilesMock).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: 'proj-trek' }),
    )
  })

  it('omits project_id when no filter is set', async () => {
    const { UploadsTab } = await import('../UploadsTab')
    render(<UploadsTab />)
    await Promise.resolve()
    await Promise.resolve()
    expect(listFilesMock).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: undefined }),
    )
  })
})
