import { api } from './client'

export interface AboutMeResponse {
  about_me: string | null
}

export interface UpdateAboutMeRequest {
  about_me: string | null
}

export const meApi = {
  getAboutMe: () =>
    api.get<AboutMeResponse>('/api/users/me/about-me'),

  updateAboutMe: (about_me: string | null) =>
    api.patch<AboutMeResponse>('/api/users/me/about-me', { about_me } satisfies UpdateAboutMeRequest),
}
