export interface AppSettingDto {
  key: string
  value: string
  updated_at: string
  updated_by: string
}

export interface SetSettingRequest {
  value: string
}
