import { api } from './client'

export interface VersionDto {
  version: string
  git_sha: string | null
  built_at: string | null
}

export const systemApi = {
  getVersion: () => api.get<VersionDto>('/api/version'),
}
