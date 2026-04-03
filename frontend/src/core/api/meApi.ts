import { api } from './client'
import type { UserDto } from '../types/auth'

export interface AboutMeResponse {
  about_me: string | null
}

export interface UpdateAboutMeRequest {
  about_me: string | null
}

export const meApi = {
  getMe: () =>
    api.get<UserDto>('/api/users/me'),

  getAboutMe: () =>
    api.get<AboutMeResponse>('/api/users/me/about-me'),

  updateAboutMe: (about_me: string | null) =>
    api.patch<AboutMeResponse>('/api/users/me/about-me', { about_me } satisfies UpdateAboutMeRequest),

  updateDisplayName: (display_name: string) =>
    api.patch<UserDto>('/api/users/me/profile', { display_name }),
}
